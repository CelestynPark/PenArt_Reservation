from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from pymongo import ASCENDING, IndexModel, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database

COLLECTION = "job_locks"

__all__ = [
    "COLLECTION",
    "get_collection",
    "ensure_indexes",
    "acquire",
    "renew",
    "release",
    "get"
]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _future_utc(seconds: int) -> datetime:
    if not isinstance(seconds, int) or seconds <= 0:
        raise ValueError("ttl_seconds must be positive int")
    return _now_utc() + timedelta(seconds=seconds)


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("job_key", ASCENDING)], name="uniq_job_key", unique=True),
            IndexModel([("expires_at", ASCENDING)], name="ttl_expires_at", expireAfterSeconds=0)
        ]
    )


def acquire(db: Database, *, job_key: str, owner: str, ttl_seconds: int) -> Optional[str]:
    """
    Try to acquire the lock for (job_key). Success when:
    - lock is absent or expired, or
    - lock is already owned by same owner (re-acquire/extend).
    On success returns lock id (str), else None.
    """
    if not isinstance(job_key, str) or not job_key.strip():
        raise ValueError("job_key required")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner required")
    now = _now_utc()
    new_exp = _future_utc(ttl_seconds)

    col = get_collection(db)
    doc = col.find_one_and_update(
        {
            "job_key": job_key,
            "$or": [
                {"expires_at": {"$lte": now}},
                {"owner": owner},
                {"expires_at": {"$exists": False}}, # safety for first writes
            ]
        },
        {
            "$set": {"job_key": job_key, "owner": owner, "expires_at": new_exp},
            "$setOnInsert": {"created_at": now}
        },
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    # If another owner holds a non-expired lock, filter won't match -> doc is None
    return str(doc["_id"]) if doc else None


def renew(db: Database, *, job_key: str, owner: str, ttl_seconds: int) -> bool:
    """
    Extend expiration if the caller is the current owner and lock not expired.
    Returns True if extended
    """
    if not isinstance(job_key, str) or not job_key.strip():
        raise ValueError("job_key required")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner required")
    now = _now_utc()
    new_exp = _future_utc(ttl_seconds)

    col = get_collection(db)
    res = col.find_one_and_update(
        {"job_key": job_key, "owner": owner, "expires_at": {"$gt": now}},
        {"$set": {"expires_at": new_exp}},
        return_document=ReturnDocument.AFTER
    )
    return bool(res)


def release(db: Database, *, job_key: str, owner: str) -> bool:
    """
    Release the lock only if owned by caller.
    Returns True when a lock was released.
    """
    if not isinstance(job_key, str) or not job_key.strip():
        raise ValueError("job_key required")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner required")
    col = get_collection(db)
    res = col.delete_one({"job_key": job_key, "owner": owner})
    return res.deleted_count == 1


def get(db: Database, *, job_key: str) -> Optional[dict]:
    """
    Fetch current lock document for inspection (UTC datetimes).
    """
    if not isinstance(job_key, str) or not job_key.strip():
        raise ValueError("job_key required")
    doc = get_collection(db).find_one({"job_key": job_key})
    if not doc:
        return None
    # normalize id
    doc["_id"] = str(doc.pop("_id"))
    return doc