from __future__ import annotations

from typing import Any, Dict

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "assert_insert_only",
]

collection_name = "audit_logs"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "admin_id": {"type": "objectid", "required": True},
    "action": {"type": "string", "required": True},
    "resource": {
        "type": "object",
        "schema": {
            "type": {"type": "string", "required": True},
            "id": {"type": "string", "required": True},
        },
        "required": True,
    },
    "before": {"type": "object?"},
    "after": {"type": "object?"},
    "ip": {"type": "string", "required": True},
    "ua": {"type": "string", "required": True},
    "at": {"type": "string", "format": "iso8601", "required": True},
}

indexes = [
    {"keys": [("at", -1)], "options": {"name": "at_desc", "background": True}},
    {
        "keys": [("admin_id", 1), ("at", -1)],
        "options": {"name": "admin_at_desc", "background": True},
    },
    {
        "keys": [("resource.type", 1), ("resource.id", 1), ("at", -1)],
        "options": {"name": "resource_type_id_at_desc", "background": True},
    },
]


class AppendOnlyViolation(Exception):
    code = "ERR_FORBIDDEN"


def assert_insert_only(operation: str) -> None:
    if operation != "insert":
        raise AppendOnlyViolation("audit_logs is append-only (inserts only)")
