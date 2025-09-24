from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from typing import Any, ContextManager, Dict, Optional

from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.client_session import ClientSession
from pymongo.errors import (
    DuplicateKeyError,
    PyMongoError,
    OperationFailure,
    ServerSelectionTimeoutError,
    WriteError,
)

from app.extensions import get_mongo
from app.utils.time import now_utc, isoformat_utc

__all__ = [
    "get_db",
    "get_collection",
    "start_session",
    "in_txn",
    "map_pymongo_error",
    "ttl_lock_acquire",
    "ttl_lock_release",
]


def get_db() -> Database:
    client = get_mongo()
    db = client.get_default_database()
    return db if db is not None else client["penart"]


def get_collection(name: str) -> Collection:
    return get_db()[name]


@contextmanager
def start_session() -> ContextManager[ClientSession]:
    client = get_mongo()
    session: Optional[ClientSession] = None
    try:
        session = client.start_session()
        yield session
    finally:
        if session is not None:
            session.end_session()


@contextmanager
def in_txn(session: ClientSession | None = None) -> ContextManager[ClientSession]:
    if session is not None:
        with session.start_transaction():
            yield session
        return
    with start_session() as s:
        with s.start_transaction():
            yield s


def map_pymongo_error(exc: Exception) -> Dict[str, str]:
    if isinstance(exc, DuplicateKeyError):
        return {"code": "ERR_CONFLICT", "message": "duplicate key"}
    if isinstance(exc, (WriteError, OperationFailure)):
        return {"code": "ERR_INTERNAL", "message": "db write failed"}
    if isinstance(exc, ServerSelectionTimeoutError):
        return {"code": "ERR_INTERNAL", "message": "db unavailable"}
    if isinstance(exc, PyMongoError):
        return {"code": "ERR_INTERNAL", "message": "db error"}
    return {"code": "ERR_INTERNAL", "message": "internal error"}


def _joblocks() -> Collection:
    return get_collection("job_locks")


def _now_iso() -> str:
    return isoformat_utc(now_utc())


def ttl_lock_acquire(job_key: str, owner: str, ttl_sec: int, session: ClientSession | None = None) -> bool:
    if not isinstance(job_key, str) or not job_key.strip():
        raise ValueError("job_key required")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner required")
    if not isinstance(ttl_sec, int) or ttl_sec <= 0:
        raise ValueError("ttl_sec must be positive int")

    now = now_utc()
    expires = now + timedelta(seconds=ttl_sec)
    coll = _joblocks()

    filt = {
        "job_key": job_key,
        "$or": [{"expires_at": {"$lte": now}}, {"owner": owner}],
    }
    update = {
        "$setOnInsert": {
            "job_key": job_key,
            "created_at": _now_iso(),
        },
        "$set": {
            "owner": owner,
            "expires_at": expires,
            "updated_at": _now_iso(),
        },
    }
    try:
        doc = coll.find_one_and_update(
            filt,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
            session=session,
        )
        return bool(doc and doc.get("owner") == owner and doc.get("expires_at") > now)
    except PyMongoError:
        return False


def ttl_lock_release(job_key: str, owner: str, session: ClientSession | None = None) -> bool:
    if not isinstance(job_key, str) or not job_key.strip():
        raise ValueError("job_key required")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner required")
    coll = _joblocks()
    try:
        res = coll.delete_one({"job_key": job_key, "owner": owner}, session=session)
        return res.deleted_count > 0
    except PyMongoError:
        return False
