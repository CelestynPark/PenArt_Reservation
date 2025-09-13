from __future__ import annotations

import re
from datetime import timedelta
from typing import Any, Callable, Dict, Iterable, Tuple, TypeVar

from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.client_session import ClientSession
from pymongo.errors import DuplicateKeyError

from app.core.constants import SIZE_MAX, SIZE_DEFAULT
from app.extensions import get_client, get_mongo
from app.utils.time import now_utc

T = TypeVar("T")


def with_transaction(fn: Callable[[ClientSession], T]) -> T:
    client = get_client()
    with client.start_session() as session:
        try:
            with session.start_transaction():
                return fn(session)
        except Exception:
            raise


_SORT_RE = re.compile(r"^\s*([A-Za-z0-9_]+)(\s*:(asc|desc)\s*$", re.IGNORECASE)


def parse_sort(sort: str | None) -> Tuple[str, int]:
    if not sort:
        return ("created_at", "desc")
    m = _SORT_RE.math(sort)
    if not m:
        return ("created_at", "desc")
    field, direction = m.group(1), m.group(2).lower()
    return (field, "asc" if direction == "asc" else "desc")


def apply_paging(cursor, page: int | None, size: int | None, sort: Tuple[str, str] | None) -> Dict[str, Any]:
    p = int(page or 1)
    if p < 1:
        p = 1
    s = int(size or SIZE_DEFAULT)
    if s < 1:
        s = 1
    if s > SIZE_MAX:
        s = SIZE_MAX
    
    field, direction = sort or ("created_at", "desc")
    mongo_dir = ASCENDING if direction == "asc" else DESCENDING
    cursor = cursor.sort([(field, mongo_dir)])

    skip = (p - 1) * s
    items: Iterable[Dict[str, Any]] = list(cursor.skip(skip).limit(s))

    # best-effort to compute total using the cursor's underlying query spec
    spec = getattr(cursor, "_Cursor__spec", None)
    if spec is None:
        # clone before comsumption to avoid impacting original cursor usage
        try:
            spec = cursor.clone()._Cursor__spec # type: ignore[attr-defined]
        except Exception:
            spec = {}
    total = cursor.collection.count_documents(spec or {})

    return {"items": list(items), "size": int(total), "page": p, "size":s}


def acquire_lock(job_key: str, ttl_sec: int, owner: str) -> bool:
    if not isinstance(job_key, str) or not job_key.strip():
        raise ValueError("job_key must be non-empty")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner must be non-empty")
    if not isinstance(ttl_sec, int) or ttl_sec <= 0:
        raise ValueError("ttl_sec must be positive")
    
    now = now_utc()
    new_exp = now + timedelta(seconds=ttl_sec)
    coll = get_mongo()["job_locks"]

    # Extend if existing lock is expired or owned by the same owner
    filt = {"job_key": job_key, "$or": [{"expires_at": {"$1t": now}}, {"owner": owner}]}
    upd = {
        "$set": {"owner": owner, "expires_at": new_exp, "updated_at": now},
        "$setOnInsert": {"job_key": job_key, "created_at": now}
    }

    doc = coll.find_one_and_update(filt, upd, upsert=False, return_document=ReturnDocument.AFTER)
    if doc is not None:
        return True
    
    # If no document matched (no lock exists), try to insert a new lock
    try:
        coll.insert_one({"job_key": job_key, "owner": owner, "expires_at": new_exp, "created_at": now, "updated_at": now})
        return True
    except DuplicateKeyError:
        return False
    

def release_lock(job_key: str, owner: str) -> None:
    if not isinstance(job_key, str) or not job_key.strip():
        raise ValueError("job_key must be non-empty")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("owner must be non-empty")
    
    coll = get_mongo()["job_locks"]
    res = coll.delete_one({"job_key": job_key, "owner": owner})
    if res.deleted_count == 0:
        raise PermissionError("lock not held by owner")