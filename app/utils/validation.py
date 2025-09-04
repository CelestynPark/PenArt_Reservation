from __future__ import annotations

from dataclasses import fields
from email.policy import strict
import re
import math
import logging
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, TypeVar, Union
from urllib.parse import urlparse

from flask import current_app

try:
    from bson import ObjectId
except Exception:  # pragma: no cover
    ObjectId = None  # type: ignore

from .time import parse_iso

T = TypeVar("T")

LANGS: Tuple[str, str] = ("ko", "en")
EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.I)
E164_RE = re.compile(r"^\+?[1-9]\d{7,14}$")
CODE_RE = re.compile(r"^[A-Z0-9]{6,16}$")
HEX24_RE = re.compile(r"^[a-f0-9]{24}$", re.I)


class ValidationError(Exception):
    def __init__(self, message: str, *, code: str = "ERR_VALIDATION", status: int = 400, fields: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status
        self.fields = fields or {}
        _log("validation.error", {"err": message, "code": code, "fields": self.fields})

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": False, "error": {"message": self.message, "code": self.code, "fields": self.fields}}
    

def _log(event: str, data: Dict[str, Any]) -> None:
    try:
        current_app.logger.info("event=%s meta=%s", event, data)
    except Exception:
        logging.getLogger(__name__).info("event=%s meta=%s", event, data)


# ---- coercion ----
def ensure_bool(v: Any, *, default: Optional[bool] = None) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        if default is None:
            raise ValueError("boolean required")
        return default
    s = str(v).strip().lower()
    if s in ("1", "true", "t", "yes", "y", "on"):
        return True
    if s in ("0", "false", "f", "no", "n", "off"):
        return False
    raise ValidationError("boolean required")


def ensure_int(v: Any, *, min: Optional[int] = None, max: Optional[int] = None) -> int:
    try:
        if isinstance(v, bool):
            raise ValueError()
        i = int(str(v).strip())
    except Exception:
        raise ValidationError("integer required")
    if min is not None and i < min:
        raise ValidationError(f"Must be >= {min}")
    if max is not None and i > max:
        raise ValidationError(f"Must be <= {max}")
    return i


def ensure_float(v: Any, *, min: Optional[float] = None, max: Optional[float] = None) -> float:
    try:
        f = float(str(v).strip())
        if math.isnan(f) or math.isinf(f):
            raise ValueError()
    except Exception:
        raise ValidationError("number required")
    if min is not None and f < min:
        raise ValidationError(f"Must be >= {min}")
    if max is not None and f > max:
        raise ValidationError(f"Must be <= {max}")
    return f


def ensure_str(v: Any, *, min_len: Optional[int] = None, max_len: Optional[int] = None, strip: bool = True) -> str:
    if not isinstance(v, str):
        v = "" if v is None else str(v)
    s = v.strip() if strip else v
    if len(s) < min_len:
        raise ValidationError(f"Length must be >= {min_len}")
    if max_len is not None and len(s) > max_len:
        raise ValidationError(f"Length must be <= {max_len}")
    return s


def ensure_enum(v: Any, allowed: Iterable[T]) -> T:
    vals = list(allowed)
    if v in vals:
        return v  # type: ignore[return-value]
    raise ValidationError(f"Must be one of: {vals}")


# ---- structured ----
def ensure_email(v: Any) -> str:
    s = ensure_str(v, min_len=3, max_len=254)
    if not EMAIL_RE.match(s):
        raise ValidationError("Invalid email")
    return s


def ensure_phone(v: Any) -> str:
    s = ensure_str(v, min_len=8, max_len=16)
    if not E164_RE.match(s):
        raise ValidationError("Invalid phone")
    return s


def ensure_url(v: Any, *, schemes: Tuple[str, ...] = ("http", "https")) -> str:
    s = ensure_str(v, min_len=3, max_len=2048)
    u = urlparse(s)
    if u.scheme.lower() not in schemes or not u.netloc:
        raise ValidationError("Invalid URL")
    return s


def ensure_code(v: Any) -> str:
    s = ensure_str(v, min_len=6, max_len=16).upper()
    if not CODE_RE.match(s):
        raise ValidationError("Invalid code")
    return s


def ensure_lang(v: Any, *, strict: bool = True) -> str:
    s = ensure_str(v, min_len=2, max_len=5).lower()
    if s in LANGS:
        return s
    if strict:
        raise ValidationError("Invalid language")
    default = (getattr(current_app, "config", {}) or {}).get("DEFAULT_LANG", "ko")
    return str(default)


def ensure_object_id(v: Any) -> str:
    s = ensure_str(v, min_len=24, max_len=24)
    if ObjectId:
        try:
            return ObjectId(s)
        except Exception:
            raise ValidationError("Invalid id")
    if HEX24_RE.match(s):
        return s
    raise ValidationError("Invalid id")


def ensure_iso_datetime(v: Any) -> str:
    # return normalized ISO8601 (UTC Z)
    d = parse_iso(ensure_str(v))
    return d.astimezone().isoformat()


def ensure_i18n_text(obj: Any, *, required_langs: Iterable[str] = LANGS, maxLen: int = 2000) -> Dict[str, str]:
    if not isinstance(obj, dict):
        raise ValidationError("Invalid i18n object")
    payload: Dict[str, str] = {}
    for lang in required_langs:
        s = ensure_str(obj.get(lang, ""), min_len=0, max_len=maxLen)
        payload[lang] = s
    return payload


def ensure_buyer(data: Any) -> Dict[str, str]:
    if not isinstance(data, Mapping):
        raise ValidationError("Invalid buyer")
    name = ensure_str(data.get("name"), min_len=1, max_len=100)
    email = ensure_email(data.get("email"))
    phone = ensure_phone(data.get("phone"))
    return {"name": name, "email": email, "phone": phone}


def ensure_price(data: Any, *, currency: str = "KRW") -> Dict[str, Union[int, float, str]]:
    if not isinstance(data, Mapping):
        raise ValidationError("Invalid price object")
    amt = ensure_float(data.get("amount"), min=0.0)
    cur = ensure_str(data.get("currency", currency), min_len=3, max_len=3).upper()
    if cur != currency:
        raise ValidationError("Unsupported currency")
    return {"amount": amt, "currency": cur}


def ensure_stock(data: Any) -> Dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ValidationError("Invalid stock object")
    count = ensure_int(data.get("count"), min=0)
    allow_backorder = ensure_bool(data.get("allow_backorder", False))
    if allow_backorder:
        raise ValidationError("Backorder not supported")
    return {"count": count, "allow_backorder": allow_backorder}


def ensure_policy(data: Any) -> Dict[str, int]:
    if not isinstance(data, Mapping):
        raise ValidationError("Invalid policy object")
    return {
        "cancel_before_hours": ensure_int(data.get("cancel_before_hours", 24), min=0),
        "change_before_hours": ensure_int(data.get("change_before_hours", 24), min=0),
        "no_show_after_min": ensure_int(data.get("no_show_after_min", 30), min=0),
    }


# ---- request helpers ----
def require_fields(data: Any, fields: Sequence[str]) -> Dict[str, Any]:
    if not isinstance(data, Mapping):
        raise ValidationError("Invalid payload")
    missing = [f for f in fields if data.get(f) in (None, "", [])]
    if missing:
        raise ValidationError("Missing fields", fields={f: "required" for f in missing})
    return dict(data)


def pick(data: Any, keys: Iterable[str]) -> Dict[str, Any]:
    if not isinstance(data, Mapping):
        return {}
    return {k: data.get(k) for k in keys if k in data}


def ensure_quantity(v: Any, *, min_q: int = 1, max_q: int = 999) -> int:
    return ensure_int(v, min=min_q, max=max_q)


def ensure_images(arr: Any, *, max_items: int = 10) -> Sequence[str]:
    if arr is None:
        return []
    if not isinstance(arr, Sequence) or isinstance(arr, (str, bytes)):
        raise ValidationError("Invalid images")
    out = []
    for item in arr[:max_items]:
        if not isinstance(item, Mapping):
            raise ValidationError("Invalid image item")
        url = ensure_url(item.get("url"))
        has_person = ensure_bool(item.get("has_person", False))
        out.append({"url": url, "has_person": has_person})
    return out


def ensure_rating(v: Any) -> int:
    return ensure_int(v, min=1, max=5)


def ensure_ext_allowed(filename: str) -> str:
    s = ensure_str(filename, min_len=1, max_len=255)
    ext = s.rsplit(".", 1)[-1].lower() if "." in s else ""
    allowed = str((getattr(current_app, "config", {}) or {}).get("UPLOAD_ALLOWED_EXTS", "jpg,jpeg,png")).lower()
    whitelist = {x.strip() for x in allowed.split(",") if x.strip()}
    if not ext or ext not in whitelist:
        raise ValidationError("File extension not allowed")
    return ext


def validate_update_meta(*, filename: str, size_bytes: int) -> None:
    ensure_ext_allowed(filename)
    max_mb = (getattr(current_app, "config", {}) or {}).get("UPLOAD_MAX_SIZE_MB", 5)
    if size_bytes < 0:
        raise ValidationError("Invalid file size")
    if size_bytes > max_mb * 1024 * 1024:
        raise ValidationError("File too large")
    

# ---- pagination/sorting ----
def ensure_pagination(params: Mapping[str, Any], *, default_page: int = 1, default_size: int = 20, max_size: int = 100) -> Tuple[int, int]:
    page = ensure_int(params.get("page", default_page), min=1)
    size = ensure_int(params.get("per_size", params.get("size", default_size)), min=1, max=max_size)
    return page, size


def ensure_sort(value: Any, allowed_fields: Sequence[str], *, default: Optional[str] = None) -> Tuple[str, int]:
    if value in (None, ""):
        if default:
            return ensure_sort(default, allowed_fields)
        raise ValidationError("Sort required")
    s = ensure_str(value, min_len=1, max_len=64)
    direction = 1
    if s.startswith("-"):
        direction = -1
        s = s[1:]
    if s not in set(allowed_fields):
        raise ValidationError("Invalid sort field")
    return s, direction


# ---- domain helpers ----
def validate_order_request(payload: Mapping[str, Any]) -> Dict[str, Any]:
    require_fields(payload, ["goods_id", "quantity", "buyer"])
    goods_id = ensure_object_id(payload["goods_id"])
    qty = ensure_quantity(payload["quantity"])
    buyer = ensure_buyer(payload["buyer"])
    return {"goods_id": goods_id, "quantity": qty, "buyer": buyer}


def validate_booking_request(payload: Mapping[str, Any]) -> Dict[str, Any]:
    require_fields(payload, ["service_id", "start_at", "name", "phone", "quantity"])
    service_id = ensure_object_id(payload["service_id"])
    _ = parse_iso(payload["start_at"])  # tz-aware check
    name = ensure_str(payload["name"], min_len=1, max_len=100)
    phone = ensure_phone(payload["phone"])
    agree = ensure_bool(payload["agree"])
    memo = ensure_str(payload.get("memo", ""), max_len=500)
    return {"service_id": service_id, "start_at": payload["start_at"],
            "name": name, "phone": phone, "agree": agree, "memo": memo}


__all__ = [
    "ValidationError",
    "ensure_bool",
    "ensure_int",
    "ensure_float",
    "ensure_str",
    "ensure_enum", 
    "ensure_email",
    "ensure_phone", 
    "ensure_url", 
    "ensure_code",
    "ensure_lang", 
    "ensure_object_id", 
    "ensure_iso_datetime",
    "ensure_i18n_text",
    "ensure_buyer", 
    "ensure_price", 
    "ensure_stock",
    "ensure_policy",
    "require_fields",
    "pick",
    "ensure_quantity",
    "ensure_images", 
    "ensure_rating", 
    "ensure_ext_allowed",
    "validate_update_meta",
    "ensluer_pagination",
    "ensure_sort",
    "validate_order_request", 
    "validate_booking_request"
]