from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from app.models.base import TIMESTAMP_FIELDS
from app.utils.time import isoformat_utc, now_utc

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "can_write_review",
]

collection_name = "reviews"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "booking_id": {"type": "string", "required": True},
    "customer_id": {"type": "string", "required": True},
    "rating": {"type": "int", "min": 1, "max": 5, "required": True},
    "quote_i18n": {
        "type": "object",
        "schema": {"ko": {"type": "string", "required": True}, "en": {"type": "string?"}},
        "required": True,
    },
    "comment_i18n": {
        "type": "object",
        "schema": {"ko": {"type": "string?"}, "en": {"type": "string?"}},
        "default": {},
    },
    "images": {
        "type": "array",
        "items": {
            "type": "object",
            "schema": {
                "url": {"type": "string", "required": True},
                "has_person": {"type": "bool", "default": False},
            },
        },
        "default": [],
    },
    "status": {"type": "string", "enum": ["published", "hidden", "flagged"], "default": "published"},
    "moderation": {
        "type": "object",
        "schema": {"status": {"type": "string?"}, "reason": {"type": "string?"}},
        "default": {},
    },
    "helpful_count": {"type": "int", "default": 0},
    "reported_count": {"type": "int", "default": 0},
    TIMESTAMP_FIELDS[0]: {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[1]: {"type": "string?", "format": "iso8601"},
}

indexes = [
    {"keys": [("booking_id", 1)], "options": {"name": "booking_id_1", "unique": True, "background": True}},
    {"keys": [("status", 1), ("created_at", -1)], "options": {"name": "status_1_created_at_-1", "background": True}},
]

DEFAULT_REVIEW_WINDOW_DAYS = 30
ALLOWED_BOOKING_STATUS_FOR_REVIEW = {"completed"}


def can_write_review(booking_status: str, completed_within_days: int) -> bool:
    try:
        days = int(completed_within_days)
    except Exception:
        return False
    if booking_status not in ALLOWED_BOOKING_STATUS_FOR_REVIEW:
        return False
    if days < 0:
        return False
    return days <= DEFAULT_REVIEW_WINDOW_DAYS
