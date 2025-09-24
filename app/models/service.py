from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from app.models.base import TIMESTAMP_FIELDS
from app.utils.time import isoformat_utc, now_utc

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "normalize_service",
]


collection_name = "services"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "name_i18n": {"type": "object", "schema": {"ko": {"type": "string"}, "en": {"type": "string?"}}, "required": True},
    "description_i18n": {"type": "object", "schema": {"ko": {"type": "string?"}, "en": {"type": "string?"}}, "default": {}},
    "prerequisites_i18n": {
        "type": "object",
        "schema": {"ko": {"type": "string?"}, "en": {"type": "string?"}},
        "default": {},
    },
    "materials_i18n": {"type": "object", "schema": {"ko": {"type": "string?"}, "en": {"type": "string?"}}, "default": {}},
    "images": {"type": "array", "items": {"type": "string"}, "default": []},
    "duration_min": {"type": "int", "required": True},
    "level": {"type": "string?", "default": None},
    "policy": {
        "type": "object",
        "schema": {
            "cancel_before_hours": {"type": "int", "min": 0},
            "change_before_hours": {"type": "int", "min": 0},
            "no_show_after_min": {"type": "int", "min": 0},
        },
        "required": True,
    },
    "auto_confirm": {"type": "bool", "default": False},
    "is_active": {"type": "bool", "default": True},
    "order": {"type": "int", "default": 0},
    "is_featured": {"type": "bool", "default": False},
    TIMESTAMP_FIELDS[0]: {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[1]: {"type": "string?", "format": "iso8601"},
}

indexes = [
    {"keys": [("is_active", 1), ("order", 1)], "options": {"name": "is_active_1_order_1", "background": True}},
]


class ServicePayloadError(ValueError):
    code = "ERR_INVALID_PAYLOAD"


def _ensure_mapping(doc: Mapping) -> None:
    if not isinstance(doc, Mapping):
        raise ServicePayloadError("document must be a mapping/dict")


def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _clean_str(v: Optional[Any]) -> Optional[str]:
    return v.strip() if isinstance(v, str) else None


def _unique_trimmed(items: Iterable[str]) -> list[str]:
    seen = set()
    out: list[str] = []
    for x in items or []:
        if not isinstance(x, str):
            continue
        t = x.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _norm_i18n(obj: Mapping[str, Any] | None, require_ko: bool = False) -> Dict[str, Optional[str]]:
    o = dict(obj or {})
    ko = _clean_str(o.get("ko")) or ""
    en = _clean_str(o.get("en")) or None
    if require_ko and not ko:
        raise ServicePayloadError("name_i18n.ko is required")
    return {"ko": ko, "en": en}


def _norm_int(v: Any, field: str, min_value: Optional[int] = None) -> int:
    try:
        iv = int(v)
    except Exception as e:
        raise ServicePayloadError(f"{field} must be integer") from e
    if min_value is not None and iv < min_value:
        raise ServicePayloadError(f"{field} must be ≥ {min_value}")
    return iv


def normalize_service(doc: Mapping[str, Any]) -> Dict[str, Any]:
    _ensure_mapping(doc)
    src = deepcopy(dict(doc))
    out: MutableMapping[str, Any] = {}

    out["name_i18n"] = _norm_i18n(src.get("name_i18n"), require_ko=True)
    out["description_i18n"] = _norm_i18n(src.get("description_i18n"), require_ko=False)
    out["prerequisites_i18n"] = _norm_i18n(src.get("prerequisites_i18n"), require_ko=False)
    out["materials_i18n"] = _norm_i18n(src.get("materials_i18n"), require_ko=False)

    out["images"] = _unique_trimmed(src.get("images") or [])

    if "duration_min" not in src:
        raise ServicePayloadError("duration_min is required")
    out["duration_min"] = _norm_int(src.get("duration_min"), "duration_min", min_value=1)

    out["level"] = _clean_str(src.get("level")) or None

    pol = dict(src.get("policy") or {})
    if "cancel_before_hours" not in pol or "change_before_hours" not in pol or "no_show_after_min" not in pol:
        raise ServicePayloadError("policy.cancel_before_hours|change_before_hours|no_show_after_min are required")
    policy_norm = {
        "cancel_before_hours": _norm_int(pol.get("cancel_before_hours"), "policy.cancel_before_hours", min_value=0),
        "change_before_hours": _norm_int(pol.get("change_before_hours"), "policy.change_before_hours", min_value=0),
        "no_show_after_min": _norm_int(pol.get("no_show_after_min"), "policy.no_show_after_min", min_value=0),
    }
    out["policy"] = policy_norm

    auto_confirm = src.get("auto_confirm")
    out["auto_confirm"] = bool(auto_confirm) if isinstance(auto_confirm, bool) else False

    is_active = src.get("is_active")
    out["is_active"] = bool(is_active) if isinstance(is_active, bool) else True

    order = src.get("order", 0)
    out["order"] = _norm_int(order, "order", min_value=0)

    is_featured = src.get("is_featured")
    out["is_featured"] = bool(is_featured) if isinstance(is_featured, bool) else False

    # timestamps
    now_iso = _now_iso()
    created = _clean_str(src.get(TIMESTAMP_FIELDS[0]))
    updated = _clean_str(src.get(TIMESTAMP_FIELDS[1]))
    out[TIMESTAMP_FIELDS[0]] = created or now_iso
    out[TIMESTAMP_FIELDS[1]] = updated or now_iso

    return dict(out)
