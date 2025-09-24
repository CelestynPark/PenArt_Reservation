from __future__ import annotations

from typing import Any, Dict

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
]

collection_name = "notifications_logs"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "to": {"type": "string", "required": True},
    "channel": {"type": "string", "allowed": ["email", "sms", "kakao"], "required": True},
    "template": {"type": "string", "required": True},
    "payload": {"type": "object", "required": True},
    "status": {"type": "string", "allowed": ["sent", "failed"], "required": True},
    "error": {"type": "string?"},
    "at": {"type": "string", "format": "iso8601", "required": True},
}

indexes = [
    {"keys": [("at", -1)], "options": {"name": "at_desc", "background": True}},
    {
        "keys": [("channel", 1), ("at", -1)],
        "options": {"name": "channel_at_desc", "background": True},
    },
    {
        "keys": [("status", 1), ("at", -1)],
        "options": {"name": "status_at_desc", "background": True},
    },
    {"keys": [("to", 1), ("at", -1)], "options": {"name": "to_at_desc", "background": True}},
]
