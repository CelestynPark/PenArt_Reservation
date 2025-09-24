from __future__ import annotations

from typing import Any, Dict

from app.models.base import TIMESTAMP_FIELDS

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
]

collection_name = "works"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "author_type": {"type": "string", "enum": ["artist", "student"], "required": True},
    "title_i18n": {
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
    "tags": {"type": "array", "items": {"type": "string"}, "default": []},
    "is_visible": {"type": "bool", "default": True},
    "order": {"type": "int", "default": 0},
    TIMESTAMP_FIELDS[0]: {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[1]: {"type": "string?", "format": "iso8601"},
}

indexes = [
    {
        "keys": [("author_type", 1), ("is_visible", 1), ("order", 1)],
        "options": {"name": "author_type_1_is_visible_1_order_1", "background": True},
    },
]
