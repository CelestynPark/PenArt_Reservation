from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from app.config import load_config
from app.models.base import TIMESTAMP_FIELDS
from app.utils.time import isoformat_utc, now_utc

try:
    from app.utils.phone import normalize_phone as _normalize_phone  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _normalize_phone = None


__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "normalize_studio",
]

collection_name = "studio"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "name": {"type": "string", "required": True, "max": 200},
    "bio_i18n": {"type": "object", "schema": {"ko": {"type": "string?"}, "en": {"type": "string?"}}},
    "avatar": {"type": "string?"},
    "styles": {"type": "array", "items": {"type": "string"}, "default": []},
    "address": {
        "type": "object",
        "schema": {"text": {"type": "string?"}, "lat": {"type": "number?"}, "lng": {"type": "number?"}},
        "default": {},
    },
    "hours": {"type": "object?", "default": {}},
    "notice_i18n": {"type": "object", "schema": {"ko": {"type": "string?"}, "en": {"type": "string?"}}, "default": {}},
    "contact": {
        "type": "object",
        "schema": {"phone": {"type": "string?"}, "email": {"type": "string?"}, "sns": {"type": "object?", "default": {}}},
        "default": {},
    },
    "map": {"type": "object", "schema": {"naver_client_id": {"type": "string?"}}, "default": {}},
    "is_active": {"type": "bool", "default": True},
    TIMESTAMP_FIELDS[0]: {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[1]: {"type": "string?", "format": "iso8601"},
}

indexes = [
    {"keys": [("is_active", 1)], "options": {"name": "is_active_1", "background": True}},
]


class StudioPayloadError(ValueError):
    code = "ERR_INVALID_PAYLOAD"


def _ensure_mapping(doc: Mapping) -> None:
    if not isinstance(doc, Mapping):
        raise StudioPayloadError("document must be a mapping/dict")


def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _clean_str(v: Optional[Any]) -> Optional[str]:
    return v.strip() if isinstance(v, str) else None


def _clean_email(v: Optional[Any]) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise StudioPayloadError("email must be string")
    e = v.strip().lower()
    if not e:
        return None
    if "@" not in e or e.startswith("@") or e.endswith("@"):
        raise StudioPayloadError("invalid email format")
    return e


def _fallback_normalize_phone_kr(v: str) -> str:
    s = re.sub(r"[^\d]", "", v or "")
    if not s:
        return ""
    if s.startswith("82"):
        s = s[2:]
    if s.startswith("0"):
        s = s[1:]
    if not (s.startswith("10") and len(s) in (9, 10, 11)):
        raise StudioPayloadError("invalid KR phone")
    if len(s) == 9:
        s = "0" + s
    mid = s[2:6]
    tail = s[6:]
    return f"+82-10-{mid}-{tail}"


def _normalize_phone(v: Optional[Any]) -> Optional[str]:
    if v is None:
        return None
    s = str(v)
    if not s.strip():
        return None
    if _normalize_phone is not None:  # type: ignore[truthy-function]
        try:
            return _normalize_phone(s)  # type: ignore[misc]
        except Exception as e:  # pragma: no cover
            raise StudioPayloadError(str(e))
    return _fallback_normalize_phone_kr(s)


def _unique_trimmed(items: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for x in items or []:
        if not isinstance(x, str):
            continue
        t = x.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _norm_i18n(obj: Mapping[str, Any] | None) -> Dict[str, Optional[str]]:
    o = dict(obj or {})
    ko = _clean_str(o.get("ko")) or ""
    en = _clean_str(o.get("en")) or None
    return {"ko": ko, "en": en}


def normalize_studio(doc: Mapping[str, Any]) -> Dict[str, Any]:
    _ensure_mapping(doc)
    cfg = load_config()
    out: MutableMapping[str, Any] = deepcopy(dict(doc))

    name = _clean_str(out.get("name"))
    if not name:
        raise StudioPayloadError("name is required")
    out["name"] = name

    out["bio_i18n"] = _norm_i18n(out.get("bio_i18n"))
    out["notice_i18n"] = _norm_i18n(out.get("notice_i18n"))

    avatar = _clean_str(out.get("avatar"))
    out["avatar"] = avatar or None

    out["styles"] = _unique_trimmed(out.get("styles") or [])

    addr = dict(out.get("address") or {})
    addr_text = _clean_str(addr.get("text"))
    lat = addr.get("lat")
    lng = addr.get("lng")
    addr_norm = {
        "text": addr_text or None,
        "lat": float(lat) if isinstance(lat, (int, float, str)) and str(lat).strip() != "" else None,
        "lng": float(lng) if isinstance(lng, (int, float, str)) and str(lng).strip() != "" else None,
    }
    out["address"] = addr_norm

    hours = out.get("hours") or {}
    out["hours"] = hours if isinstance(hours, Mapping) else {}

    contact = dict(out.get("contact") or {})
    out["contact"] = {
        "phone": _normalize_phone(contact.get("phone")),
        "email": _clean_email(contact.get("email")),
        "sns": contact.get("sns") if isinstance(contact.get("sns"), Mapping) else {},
    }

    mp = dict(out.get("map") or {})
    naver_id = _clean_str(mp.get("naver_client_id")) or _clean_str(cfg.naver_map.naver_client_id)
    out["map"] = {"naver_client_id": naver_id or None}

    is_active = out.get("is_active")
    out["is_active"] = bool(is_active) if isinstance(is_active, bool) else True

    for f in TIMESTAMP_FIELDS:
        if not out.get(f):
            out[f] = _now_iso()

    return dict(out)
