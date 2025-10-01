from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.core.constants import API_DATA_KEY, API_ERROR_KEY, API_OK_KEY, ErrorCode
from app.repositories import service as repo
from app.services.i18n_service import available_langs

__all__ = ["list_active", "get_detail", "merge_policy"]

DEFAULT_SORT = "order:asc"


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {API_OK_KEY: True, API_DATA_KEY: data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": message}}


def _lang_key(lang: Optional[str]) -> str:
    l = (lang or "ko").strip().lower()
    return l if l in available_langs() else "ko"


def _merge_i18n(obj: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    o = dict(obj or {})
    ko = o.get("ko") if isinstance(o.get("ko"), str) else ""
    en = o.get("en") if isinstance(o.get("en"), str) else None
    if (en is None or (isinstance(en, str) and en.strip() == "")) and isinstance(ko, str):
        en = ko or None
    return {"ko": ko, "en": en}


def _id_of(doc: Dict[str, Any]) -> str:
    v = doc.get("_id") or doc.get("id")
    return str(v)


def merge_policy(service_doc: Dict[str, Any]) -> Dict[str, int]:
    p = dict((service_doc or {}).get("policy") or {})
    try:
        cancel_before_hours = int(p.get("cancel_before_hours", 0))
        change_before_hours = int(p.get("change_before_hours", 0))
        no_show_after_min = int(p.get("no_show_after_min", 0))
    except Exception:
        raise ValueError("invalid policy values")
    if cancel_before_hours < 0 or change_before_hours < 0 or no_show_after_min < 0:
        raise ValueError("policy values must be non-negative")
    return {
        "cancel_before_hours": cancel_before_hours,
        "change_before_hours": change_before_hours,
        "no_show_after_min": no_show_after_min
    }


def _view_item(doc: Dict[str, Any], lang: str) -> Dict[str, Any]:
    return {
        "id": _id_of(doc),
        "name_i18n": _merge_i18n(doc.get("name_i18n")),
        "duration_min": int(doc.get("duration_min") or 0),
        "level": doc.get("level"),
        "is_active": bool(doc.get("is_active", True)),
        "auto_confirm": bool(doc.get("auto_confirm", False)),
        "policy": merge_policy(doc)
    }


def _view_detail(doc: Dict[str, Any], lang: str) -> Dict[str, Any]:
    base = _view_item(doc, lang)
    base.update(
        {
            "images": list(doc.get("images") or []),
            "description_i18n": _merge_i18n(doc.get("description_i18n")),
            "prerequisites_i18n": _merge_i18n(doc.get("prerequisites_i18n")),
            "materials_i18n": _merge_i18n(doc.get("materials_i18n"))
        }
    )
    return base


def list_active(lang: str = "ko", page: int = 1, size: int = 20, sort: str = DEFAULT_SORT) -> Dict[str, Any]:
    try:
        key_lang = _lang_key(lang)
        res = repo.list_active(page=page, size=size, sort=sort or DEFAULT_SORT)
        items = [_view_item(doc, key_lang) for doc in res.get("items", [])]
        data = {"items": items, "total": int(res.get("total", 0)), "page": int(res.get("page", 1)), "size": int(res.get("size", size))}
        return _ok(data)
    except repo.RepoError as e:
        code = e.code if e.code in ErrorCode.__members__.values() else ErrorCode.ERR_INTERNAL.value
        return _err(code, e.message)
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

def get_detail(service_id: str, lang: str = "ko") -> Dict[str, Any]:
    if not isinstance(service_id, str) or not service_id.strip():
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "service_id required")
    try:
        key_lang = _lang_key(lang)
        doc = repo.get_by_id(service_id.strip())
        if not doc:
            return _err(ErrorCode.ERR_NOT_FOUND.value, "service not found")
        return _ok(_view_detail(doc, key_lang))
    except repo.RepoError as e:
        code = e.code if e.code in ErrorCode.__members__.values() else ErrorCode.ERR_INTERNAL.value
        return _err(code, e.message)
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))