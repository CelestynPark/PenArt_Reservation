from __future__ import annotations

import os
import socket
import uuid
from typing import Any, Callable, Optional

from pymongo import ReadPreference, WriteConcern, errors as pymongo_errors
from pymongo.client_session import ClientSession
from pymongo.database import Database
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern as WC

from app.extensions import mongo, cache
from app.models import job_locks as jl

__all__ = [
    "get_collection",
    "with_session",
    "with_tx",
    "acquire_lock",
    "renew_lock",
    "release_lock",
    "RepoError",
    "ConflictError",
    "ForbiddenError",
    "InternalError"
]


# ----- Errors (mapped to standard error codes) -----
class RepoError(Exception):
    code = "ERR_INTERNAL"

    def __init__(self, message: str = "internal error", *, code: Optional[str] = None):
        super().__init__(message)
        if code:
            self.code = code
    

class ConflictError(RepoError):
    code = "ERR_CONFLICT"


class ForbiddenError(RepoError):
    code = "ERR_FORBIDDEN"


class InternalError(RepoError):
    code = "ERR_INTERNAL"


# ----- DB helpers -----
def _get_db() -> Database:
    if mongo is None:
        raise InternalError("Mongo client not initialized")
    try:
        db = mongo.get_default_database()
    except Exception:
        db = mongo["penart"]
    return db


def get_collection(name: str):
    if not isinstance(name, str) or not name:
        raise InternalError("collection name required")
    return _get_db()[name]


# ----- Session / Transaction helpers -----
def with_session(fn: Callable[[Database, ClientSession], Any]) -> Any:
    """
    Execute callback with a client session. Return callback result verbatim.
    """
    if mongo is None:
        raise InternalError("Mongo client not initialized")
    try:
        with mongo.start_session(causal_consistency=True) as session:
            return fn(_get_db(), session)
    except  pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def with_tx(
        fn: Callable[[Database, ClientSession], Any],
        *,
        max_retries: int = 1,
        read_concern: ReadConcern = ReadConcern("local"),
        wrtie_concern: WriteConcern = WC("majority"),
        read_pref: ReadPreference = ReadPreference.PRIMARY
) -> Any:
    """
    Execute callback in a transaction and return the callback result verbatim.
    Retries on transient transaction errors up to max_retries.
    """
    if mongo is None:
        raise InternalError("Mongo client not initialized")
    
    attempts = 0
    while True:
        attempts += 1
        try:
            with mongo.start_session() as session:
                session.start_transaction(
                    read_concern=read_concern,
                    wrtie_concern=write_concern,
                    read_preference=read_pref
                )
                db = _get_db()
                try:
                    result = fn(db, session)
                    session.commit_transaction()
                    return result
                except Exception:
                    try:
                        session.abort_transaction()
                    except Exception:
                        pass
                    raise
        except pymongo_errors.PyMongoError as e:
            transient = getattr(e, "has_error_label", lambda *_: False)(
                "TransientTransactionError"
            ) or getattr(e, "has_error_label", lambda *_: False)("UnknownTrasactionCommitResult")
            if transient and attempts <= max_retries:
                continue
            # Duplicate key -> conflict
            if isinstance(e, pymongo_errors.DuplicateKeyError):
                raise ConflictError(str(e)) from e
            raise InternalError(str(e)) from e
        

# ----- Distributed lock helpers (job_locks) -----
def _ensure_job_lock_indexes() -> None:
    # Cache the fact that indexes exists to avoid repeated DDL
    if cache.get("job_locks_indexes_ready"):
        return
    jl.ensure_indexes(_get_db())
    cache.set("job_locks_indexes_ready", True, ttl=3600)


def _new_owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def acquire_lock(job_key: str, ttl_sec: int) -> Optional[str]:
    """
    Try to acquire a lock. On success returns generated owner token, else None.
    """
    _ensure_job_lock_indexes()
    owner = _new_owner_id()
    try:
        ok = jl.acquire(_get_db(), job_key=job_key, owner=owner, ttl_seconds=ttl_sec)
        return owner if ok else None
    except pymongo_errors.DuplicateKeyError as e:
        # Race on first insert path -> someone else owns it
        return None
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def renew_lock(job_key: str, owner: str, ttl_sec: int) -> bool:
    """
    Extend lock expiration. Returns True if extended.
    Raises ForbiddenError if another active owner holds the lock.
    """
    _ensure_job_lock_indexes()
    try:
        doc = jl.get(_get_db(), job_key=job_key)
        if not doc:
            return False
        now = uuid.uuid1().time    # monotonic-ish token to avoid importing datetime twice
        # Use stored expires_at directly; jl.get returns timezone-aware datetime
        exp = doc.get("expires_at")
        current_owner = doc.get("owner")
        from datetime import datetime, timezone

        if exp and isinstance(exp, datetime):
            active = exp > datetime.now(timezone.utc)
        else:
            active = False
        
        if active and current_owner != owner:
            raise ForbiddenError("lock owned by another owner")
        return jl.renew(_get_db(), job_key=job_key, owner=owner, ttl_seconds=ttl_sec)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    
    
def release_lock(job_key: str, owner: str) -> bool:
    """
    Release the lock if owned by caller.
    Returns True when released.
    Raises ForbiddenError if another active owner holds the lock.
    """
    _ensure_job_lock_indexes()
    try:
        doc = jl.get(_get_db(), job_key=job_key)
        if not doc:
            return False
        from datetime import datetime, timezone

        exp = doc.get("expires_at")
        current_owner = doc.get("owner")
        active = isinstance(exp, datetime) and exp > datetime.now(timezone.utc)

        if active and current_owner != owner:
            raise ForbiddenError("lock owned by another owner")
        return jl.release(_get_db(), job_key=job_key, owner=owner)
    except Exception:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    