from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, Mapping, MutableMapping, Optional

from app.config import load_config
from app.models.base import TIMESTAMP_FIELDS
from app.utils.time import isoformat_utc, now_utc

try:
    # expected single-source phone normalizer
    from app.utils.phone import normalize_phone as _normalize_phone  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    _normalize_phone = None  # fallback defined below


__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "normalize_user",
]

collection_name = "users"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "role": {"type": "string", "enum": ["customer", "admin"], "default": "customer"},
    "name": {"type": "string?", "max": 200},
    "email": {"type": "string", "lowercase": True, "required": True},
    "phone": {"type": "string", "required": True, "format": "+82-##-####-####"},
    "lang_pref": {"type": "string", "enum": ["ko", "en"], "default": load_config().default_lang},
    "channels": {
        "type": "object",
        "schema": {
            "email": {"enabled": {"type": "bool", "default": True}, "verified_at": {"type": "string?", "format": "iso8601"}},
            "sms": {"enabled": {"type": "bool", "default": False}},
            "kakao": {"enabled": {"type": "bool", "default": False}},
        },
        "default": {},
    },
    "consents": {
        "type": "object",
        "schema": {
            "tos_at": {"type": "string?", "format": "iso8601"},
            "privacy_at": {"type": "string?", "format": "iso8601"},
        },
        "default": {},
    },
    "is_active": {"type": "bool", "default": True},
    "last_login_at": {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[0]: {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[1]: {"type": "string?", "format": "iso8601"},
}

indexes = [
    {"keys": [("email", 1)], "options": {"name": "email_1", "background": True}},
    {"keys": [("phone", 1)], "options": {"name": "phone_1", "background": True}},
    {"keys": [("name", 1)], "options": {"name": "name_1", "background": True}},
]


class UserPayloadError(ValueError):
    code = "ERR_INVALID_PAYLOAD"


def _clean_email(v: str) -> str:
    if not isinstance(v, str):
        raise UserPayloadError("email must be string")
    e = v.strip().lower()
    if not e or "@" not in e or e.startswith("@") or e.endswith("@"):
        raise UserPayloadError("invalid email format")
    return e


def _fallback_normalize_phone_kr(v: str) -> str:
    s = re.sub(r"[^\d]", "", v or "")
    if s.startswith("82"):
        s = s[2:]
    if s.startswith("0"):
        s = s[1:]
    # expect mobile 10~11 digits after stripping leading 0: 10######## or 10#########
    if not (s.startswith("10") and len(s) in (9, 10, 11)):  # tolerate some variants
        raise UserPayloadError("invalid KR phone")
    # pad if needed
    if len(s) == 9:
        s = "0" + s  # very defensive; keep structure
    if len(s) == 10:
        mid = s[2:6]
        tail = s[6:]
    else:
        mid = s[2:6] if len(s) == 11 else s[2:6]
        tail = s[6:]
    return f"+82-10-{mid}-{tail}"


def _normalize_phone(v: str) -> str:
    if _normalize_phone is not None:  # type: ignore[truthy-function]
        try:
            return _normalize_phone(v)  # type: ignore[misc]
        except Exception as e:  # pragma: no cover
            raise UserPayloadError(str(e))
    return _fallback_normalize_phone_kr(v)


def _bool(v: Optional[Any], default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "on"}
    return bool(v)


def _now_iso() -> str:
    return isoformat_utc(now_utc())


def normalize_user(doc: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(doc, Mapping):
        raise UserPayloadError("document must be a mapping/dict")

    cfg = load_config()
    out: MutableMapping[str, Any] = deepcopy(dict(doc))

    out["email"] = _clean_email(out.get("email", ""))
    out["phone"] = _normalize_phone(out.get("phone", ""))

    name = out.get("name")
    if isinstance(name, str):
        out["name"] = name.strip() or None

    lang = str(out.get("lang_pref") or "").strip().lower()
    out["lang_pref"] = lang if lang in {"ko", "en"} else cfg.default_lang

    role = str(out.get("role") or "customer").strip().lower()
    out["role"] = role if role in {"customer", "admin"} else "customer"

    channels = dict(out.get("channels") or {})
    email_ch = dict(channels.get("email") or {})
    sms_ch = dict(channels.get("sms") or {})
    kakao_ch = dict(channels.get("kakao") or {})

    channels_norm = {
        "email": {
            "enabled": _bool(email_ch.get("enabled"), True),
            "verified_at": email_ch.get("verified_at") or None,
        },
        "sms": {"enabled": _bool(sms_ch.get("enabled"), False)},
        "kakao": {"enabled": _bool(kakao_ch.get("enabled"), False)},
    }
    out["channels"] = channels_norm

    consents = dict(out.get("consents") or {})
    out["consents"] = {
        "tos_at": consents.get("tos_at") or None,
        "privacy_at": consents.get("privacy_at") or None,
    }

    out["is_active"] = _bool(out.get("is_active"), True)

    # timestamps are applied by model base helpers at repository layer; keep here if absent for idempotent upserts
    for f in TIMESTAMP_FIELDS:
        if not out.get(f):
            out[f] = _now_iso()

    return dict(out)
