from __future__ import annotations

from datetime import timedelta
from typing import Any, Dict, List

from app.models.base import utc_now, ModelPayloadError

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "acquire_lock",
    "release_lock",
    "is_locked",
]

collection_name = "job_locks"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "job_key": {"type": "string", "required": True},
    "owner": {"type": "string", "required": True},
    "expires_at": {"type": "date", "required": True},  # UTC
    "created_at": {"type": "string", "format": "iso8601", "readonly": True},
    "updated_at": {"type": "string", "format": "iso8601", "readonly": True},
}

indexes: List[Dict[str, Any]] = [
    {
        "keys": [("job_key", 1)],
        "options": {"name": "uq_job_key", "unique": True, "background": True},
    },
    {
        # TTL index: docs expire automatically once expires_at < now (Mongo handles UTC)
        "keys": [("expires_at", 1)],
        "options": {"name": "ttl_expires_at", "expireAfterSeconds": 0, "background": True},
    },
]

# In-memory fallback store (tests/minimal runtime). Real deployment should use Mongo with the above indexes.
_MEM: Dict[str, Dict[str, Any]] = {}


def _cleanup_expired() -> None:
    now = utc_now()
    expired = [k for k, v in _MEM.items() if v.get("expires_at") <= now]
    for k in expired:
        _MEM.pop(k, None)


def _validate(job_key: str, owner: str) -> None:
    if not isinstance(job_key, str) or not job_key.strip():
        raise ModelPayloadError("job_key required")
    if not isinstance(owner, str) or not owner.strip():
        raise ModelPayloadError("owner required")


def acquire_lock(job_key: str, owner: str, ttl_sec: int) -> bool:
    _validate(job_key, owner)
    if not isinstance(ttl_sec, int) or ttl_sec <= 0:
        raise ModelPayloadError("ttl_sec must be positive int")
    _cleanup_expired()
    now = utc_now()
    rec = _MEM.get(job_key)
    if rec is None or rec["expires_at"] <= now:
        _MEM[job_key] = {"owner": owner, "expires_at": now + timedelta(seconds=ttl_sec)}
        return True
    if rec["owner"] == owner:
        rec["expires_at"] = now + timedelta(seconds=ttl_sec)
        _MEM[job_key] = rec
        return True
    return False


def release_lock(job_key: str, owner: str) -> bool:
    _validate(job_key, owner)
    _cleanup_expired()
    rec = _MEM.get(job_key)
    if rec and rec["owner"] == owner:
        _MEM.pop(job_key, None)
        return True
    return False


def is_locked(job_key: str) -> bool:
    if not isinstance(job_key, str) or not job_key.strip():
        raise ModelPayloadError("job_key required")
    _cleanup_expired()
    rec = _MEM.get(job_key)
    return bool(rec and rec["expires_at"] > utc_now())
