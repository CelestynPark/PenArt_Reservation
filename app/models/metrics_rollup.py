from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Tuple

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "make_rollup_key",
    "period_start",
]

collection_name = "metrics_rollup"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "rollup_key": {"type": "string", "required": True},
    "period": {"type": "string", "allowed": ["daily", "weekly"], "required": True},
    "date": {"type": "string", "format": "iso8601", "required": True},
    "values": {"type": "object", "required": True},
    "created_at": {"type": "string", "format": "iso8601", "readonly": True},
    "updated_at": {"type": "string", "format": "iso8601", "readonly": True},
}

indexes = [
    {
        "keys": [("rollup_key", 1), ("period", 1), ("date", 1)],
        "options": {"name": "uq_key_period_date", "unique": True, "background": True},
    },
    {
        "keys": [("period", 1), ("date", -1)],
        "options": {"name": "period_date_desc", "background": True},
    },
]


def make_rollup_key(resource: str, variant: str | None = None) -> str:
    resource = (resource or "").strip().lower()
    if not resource:
        raise ValueError("ERR_INVALID_PAYLOAD: rollup_key resource required")
    if variant:
        v = variant.strip().lower()
        if v:
            return f"{resource}:{v}"
    return resource


def _floor_utc_day(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def period_start(date_utc: datetime, period: str) -> datetime:
    p = (period or "").lower().strip()
    start = _floor_utc_day(date_utc)
    if p == "daily":
        return start
    if p == "weekly":
        dow = (start.weekday() + 7) % 7  # Monday=0
        return start - timedelta(days=dow)
    raise ValueError("ERR_INVALID_PAYLOAD: period must be 'daily' or 'weekly'")
