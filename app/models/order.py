from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from app.models.base import TIMESTAMP_FIELDS

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "compute_expires_at",
    "snapshot_goods",
]

collection_name = "orders"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "code": {"type": "string", "required": True},
    "goods_id": {"type": "objectid", "required": True},
    "goods_snapshot": {
        "type": "object",
        "schema": {
            "name_i18n": {
                "type": "object",
                "schema": {"ko": {"type": "string", "required": True}, "en": {"type": "string?"}},
                "required": True,
            },
            "price": {
                "type": "object",
                "schema": {
                    "amount": {"type": "int", "min": 0, "required": True},
                    "currency": {"type": "string", "allowed": ["KRW"], "default": "KRW"},
                },
                "required": True,
            },
            "images": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        "required": True,
    },
    "quantity": {"type": "int", "min": 1, "required": True},
    "amount_total": {"type": "int", "min": 0, "required": True},
    "currency": {"type": "string", "allowed": ["KRW"], "default": "KRW"},
    "customer_id": {"type": "objectid?"},
    "buyer": {
        "type": "object",
        "schema": {
            "name": {"type": "string", "required": True},
            "phone": {"type": "string", "required": True},
            "email": {"type": "string", "required": True},
        },
        "required": True,
    },
    "method": {"type": "string", "allowed": ["bank_transfer"], "default": "bank_transfer"},
    "bank_snapshot": {
        "type": "object",
        "schema": {
            "bank_name": {"type": "string", "required": True},
            "account_no": {"type": "string", "required": True},
            "holder": {"type": "string", "required": True},
        },
        "required": True,
    },
    "status": {
        "type": "string",
        "enum": ["created", "awaiting_deposit", "paid", "canceled", "expired"],
        "required": True,
    },
    "receipt_image": {"type": "string?"},
    "note_customer": {"type": "string?"},
    "note_internal": {"type": "string?"},
    "history": {
        "type": "array",
        "items": {
            "type": "object",
            "schema": {
                "at": {"type": "string", "format": "iso8601", "required": True},
                "by": {"type": "string", "required": True},
                "from": {"type": "string?"},
                "to": {"type": "string?"},
                "reason": {"type": "string?"},
            },
        },
        "default": [],
    },
    "expires_at": {"type": "string", "format": "iso8601", "required": True},
    TIMESTAMP_FIELDS[0]: {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[1]: {"type": "string?", "format": "iso8601"},
}

indexes = [
    {"keys": [("code", 1)], "options": {"name": "code_1", "unique": True, "background": True}},
    {
        "keys": [("customer_id", 1), ("created_at", -1)],
        "options": {"name": "customer_created_desc", "background": True},
    },
    {
        "keys": [("status", 1), ("expires_at", 1)],
        "options": {"name": "status_expires", "background": True},
    },
]


def compute_expires_at(created_at_utc: datetime, expire_hours: int) -> datetime:
    if not isinstance(created_at_utc, datetime):
        raise ValueError("created_at_utc must be datetime")
    if not isinstance(expire_hours, int) or expire_hours <= 0:
        raise ValueError("expire_hours must be positive int")
    return created_at_utc + timedelta(hours=expire_hours)


def snapshot_goods(goods_doc: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(goods_doc, dict):
        raise ValueError("goods_doc must be dict")
    name_i18n = goods_doc.get("name_i18n") or {}
    price = goods_doc.get("price") or {}
    images = goods_doc.get("images") or []
    return {
        "name_i18n": {"ko": name_i18n.get("ko", ""), "en": name_i18n.get("en")},
        "price": {"amount": int(price.get("amount", 0)), "currency": price.get("currency", "KRW")},
        "images": list(images),
    }
