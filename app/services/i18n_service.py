from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, Optional, Set

from app.config import load_config

__all__ = ["resolve_lang", "t", "available_langs"]

_SUPPORTED: Set[str] = {"ko", "en"}


def available_langs() -> Set[str]:
    return set(_SUPPORTED)


def _normalize_lang(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = v.strip().lower()
    if v in _SUPPORTED:
        return v
    # map 'ko-KR' -> 'ko', 'en-US' -> 'en'
    if "-" in v:
        base = v.split("-", 1)[0]
        if base in _SUPPORTED:
            return base
    return None


def _parse_accept_language(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    # very small parser: pick first supported tag by order (ignores q)
    for token in header.split(","):
        code = token.split(";")[0].strip()
        lang = _normalize_lang(code)
        if lang:
            return lang
    return None


@lru_cache(maxsize=1)
def _bundles() -> Dict[str, Dict[str, Any]]:
    base_dir = os.path.join(os.path.dirname(__file__), "..", "i18n")
    bundles: Dict[str, Dict[str, Any]] = {}
    for lang in _SUPPORTED:
        path = os.path.abspath(os.path.join(base_dir, f"{lang}.json"))
        try:
            with open(path, "r", encoding="utf-8") as f:
                bundles[lang] = json.load(f)
        except Exception:
            bundles[lang] = {}
    return bundles


def _walk_key(d: Dict[str, Any], key: str) -> Optional[Any]:
    cur: Any = d
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def resolve_lang(query: Optional[str], cookie: Optional[str], header: Optional[str]) -> str:
    cfg = load_config()
    for src in (_normalize_lang(query), _normalize_lang(cookie), _parse_accept_language(header), _normalize_lang(cfg.default_lang), "ko"):
        if src in _SUPPORTED:
            return src  # type: ignore[return-value]
    return "ko"


def _format_msg(msg: str, params: Optional[Dict[str, Any]]) -> str:
    if not params:
        return msg
    try:
        return msg.format(**params)
    except Exception:
        return msg


def t(lang: str, key: str, params: Optional[Dict[str, Any]] = None) -> str:
    sel = _normalize_lang(lang) or "ko"
    bundles = _bundles()
    val = _walk_key(bundles.get(sel, {}), key)
    if isinstance(val, str):
        return _format_msg(val, params)
    # KO fallback when missing or unsupported
    val_ko = _walk_key(bundles.get("ko", {}), key)
    if isinstance(val_ko, str):
        return _format_msg(val_ko, params)
    return key
