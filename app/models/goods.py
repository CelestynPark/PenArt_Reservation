from __future__ import annotations

from typing import Any, Dict

from app.models.base import TIMESTAMP_FIELDS

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "can_sell",
]

collection_name = "goods"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "name_i18n": {
        "type": "object",
        "schema": {"ko": {"type": "string", "required": True}, "en": {"type": "string?"}},
        "required": True,
    },
    "description_i18n": {
        "type": "object",
        "schema": {"ko": {"type": "string?"}, "en": {"type": "string?"}},
        "default": {},
    },
    "images": {"type": "array", "items": {"type": "string"}, "default": []},
    "price": {
        "type": "object",
        "schema": {
            "amount": {"type": "int", "min": 0, "required": True},
            "currency": {"type": "string", "allowed": ["KRW"], "default": "KRW"},
        },
        "required": True,
    },
    "stock": {
        "type": "object",
        "schema": {
            "count": {"type": "int", "min": 0, "default": 0},
            "allow_backorder": {"type": "bool", "default": False},
        },
        "required": True,
    },
    "status": {"type": "string", "enum": ["draft", "published"], "default": "draft"},
    "contact_link": {"type": "string?"},
    "external_url": {"type": "string?"},
    TIMESTAMP_FIELDS[0]: {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[1]: {"type": "string?", "format": "iso8601"},
}

indexes = [
    {"keys": [("status", 1)], "options": {"name": "status_1", "background": True}},
    {
        "keys": [("name_i18n.ko", "text")],
        "options": {"name": "name_i18n_ko_text", "background": True},
    },
]


def can_sell(stock_count: int, allow_backorder: bool, qty: int) -> bool:
    try:
        sc = int(stock_count)
        q = int(qty)
    except Exception:
        return False
    if q <= 0 or sc < 0:
        return False
    if allow_backorder:
        return True
    return sc - q >= 0
