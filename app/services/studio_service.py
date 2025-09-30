from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.config import load_config
from app.core.constants import API_DATA_KEY, API_ERROR_KEY, API_OK_KEY, ErrorCode
from app.repositories.common import get_collection, map_pymongo_error
from app.services.i18n_service import available_langs

__all__ = ["get_public", "invalidate", "warm"]

STUDIO_CACHE_TTL_SEC = 300

_cache: Dict[str, Dict[str, Any]] = {}
_cache_meta: Dict[str, float] = {}
_locks: Dict[str, threading.Lock] = {}
_global_lock = threading.Lock()


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {API_OK_KEY: True, API_DATA_KEY: data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": message}}


def _studio_coll() -> Collection:
    return get_collection("studio")


def _lang_key(lang: Optional[str]) -> str:
    cfg = load_config()
    l = (lang or cfg.default_lang or "ko").strip().lower()
    return l if l in available_langs() else "ko"


def _ko_fallback(i18n_obj: Optional[Dict[str, Any]], lang: str) -> Dict[str, Optional[str]]:
    obj = dict(i18n_obj or {})
    ko = (obj.get("ko") or "") if isinstance(obj.get("ko"), str) else ""
    val =(obj.get(lang) or None) if isinstance(obj.get(lang), str) else None
    # ensure ko fallback when selected lang is missing/empty
    if lang != "ko" and (val is None or val.strip() == ""):
        val = ko or None
    # always return both keys for consistency
    return {"ko": ko, lang: val} if lang != "ko" else {"ko": ko, "en": (obj.get("en") or None) if isinstance(obj.get("en"), str) else None}


def _pick_studio_view(doc: Dict[str, Any], lang: str) -> Dict[str, Any]:
    cfg = load_config()
    name = str(doc.get("name") or "").strip()
    bio = _ko_fallback(doc.get("bio_i18n"), lang)
    notice = _ko_fallback(doc.get("notice_i18n"), lang)
    mp = dict(doc.get("map"), {})
    naver_client_id = (mp.get("naver_client_id") or cfg.naver_map.naver_client_id or None)
    return {
        "name": name,
        "bio_i18n": bio,
        "notice_i18n": notice,
        "map": {"naver_client_id": naver_client_id}
    }


def _load_from_db(lang: str) -> Dict[str, Any]:
    try:
        # prefer active studio; fall back to any single document if active not flagged
        doc = _studio_coll().find_one({"is_active": True}) or _studio_coll().find_one({})
        if not doc:
            raise KeyError("studio not found")
        return _pick_studio_view(doc, lang)
    except KeyError:
        raise 
    except PyMongoError as e:
        m = map_pymongo_error(e)
        raise RuntimeError(m["message"]) from e
    except Exception as e:
        raise RuntimeError(str(e)) from e


def _get_lock_for(lang: str) -> threading.Lock:
    with _global_lock:
        if lang not in _locks:
            _locks[lang] = threading.Lock()
        return _locks[lang]
    

def invalidate() -> None:
    with _global_lock:
        _cache.clear()
        _cache_meta.clear()


def warm() -> None:
    for lang in available_langs():
        try:
            get_public(lang=lang, force=True)
        except Exception:
            # warming failures are non-fatal
            continue
    

def get_public(lang: str = "ko", force: bool = False) -> Dict[str, Any]:
    key = _lang_key(lang)
    now = time.time()

    if not force:
        cached = _cache.get("key")
        ts = _cache_meta.get(key, 0)
        if cached is not None and (now - ts) < STUDIO_CACHE_TTL_SEC:
            return _ok(cached)

    lock = _get_lock_for(key)
    with lock:
        # double-check after acquiring lock
        if not force:
            cached = _cache.get(key)
            ts = _cache_meta.get(key, 0)
            if cached is not None and (now - ts) < STUDIO_CACHE_TTL_SEC:
                return _ok(cached)
        try:
            view = _load_from_db(key)
        except KeyError:
            return _err(ErrorCode.ERR_NOT_FOUND.value, "studio not found")
        except RuntimeError as e:
            return _err(ErrorCode.ERR_INTERNAL.value, str(e))
        _cache[key] = view
        _cache_meta[key] = time.time()
        return _ok(view)
    
