from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

from flask import has_request_context, request
from pymongo import ReturnDocument
from pymongo.collection import Collection

from app.config import load_config
from app.extensions import get_mongo

__all__ = ["RateLimitError", "rate_limit_key", "check_rate_limit", "remaining"]


class RateLimitError(Exception):
    code = "ERR_RATE_LIMIT"
    status = 429

    def __init__(self, message: str = "Too many requests"):
        super().__init__(message)
        self.message = message


# --- helpers ---
def _now_epoch() -> int:
    return int(time.time())


def _bucket(ts: Optional[int] = None) -> int:
    return (ts or _now_epoch()) // 60


def _utc_expiry(minutes: int = 2) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def rate_limit_key(ip: str, user_id: Optional[str] = None) -> str:
    route = ""
    if has_request_context():
        try:
            route = request.path or ""
        except Exception:
            route = ""
    uid = user_id or "-"
    return f"{ip}|{uid}|{route}"


# --- Mongo backend ---
_mongo_ready = False
_mongo_lock = threading.Lock()


def _get_collection() -> Optional[Collection]:
    global _mongo_ready
    try:
        coll = get_mongo().get_database().get_collection("rate_limits")
    except Exception:
        return None
    if not _mongo_ready:
        with _mongo_lock:
            if not _mongo_ready:
                try:
                    coll.create_index("expireAt", expireAfterSeconds=0, background=True)
                    coll.create_index([("key", 1), ("bucket", 1)], unique=True, background=True)
                except Exception:
                    pass
                _mongo_ready = True
    return coll


# --- In-memory fallback (single-process only) ---
_mem_lock = threading.Lock()
_mem_store: Dict[Tuple[str, int], int] = {}


def _mem_inc(key: str, bkt: int) -> int:
    with _mem_lock:
        # cleanup old buckets opportunistically
        cur_bkt = _bucket()
        if bkt != cur_bkt:
            for k in list(_mem_store.keys()):
                if k[1] != cur_bkt:
                    _mem_store.pop(k, None)
            bkt = cur_bkt
        cnt = _mem_store.get((key, bkt), 0) + 1
        _mem_store[(key, bkt)] = cnt
        return cnt


def _mem_get(key: str, bkt: int) -> int:
    with _mem_lock:
        return _mem_store.get((key, bkt), 0)


# --- public API ---
def check_rate_limit(key: str, limit: Optional[int] = None) -> None:
    cfg = load_config()
    cap = int(limit if limit is not None else cfg.rate_limit_per_min)
    if cap <= 0:
        return
    bkt = _bucket()

    coll = _get_collection()
    if coll is not None:
        try:
            doc = coll.find_one_and_update(
                {"key": key, "bucket": bkt},
                {
                    "$inc": {"count": 1},
                    "$setOnInsert": {"expireAt": _utc_expiry(2), "key": key, "bucket": bkt},
                },
                upsert=True,
                return_document=ReturnDocument.AFTER,
                projection={"count": 1, "_id": 0},
            )
            cnt = int((doc or {}).get("count", 0))
        except Exception:
            cnt = _mem_inc(key, bkt)
    else:
        cnt = _mem_inc(key, bkt)

    if cnt > cap:
        raise RateLimitError("Rate limit exceeded")


def remaining(key: str, limit: Optional[int] = None) -> int:
    cfg = load_config()
    cap = int(limit if limit is not None else cfg.rate_limit_per_min)
    if cap <= 0:
        return cap
    bkt = _bucket()

    coll = _get_collection()
    if coll is not None:
        try:
            doc = coll.find_one({"key": key, "bucket": bkt}, {"count": 1, "_id": 0})
            used = int((doc or {}).get("count", 0))
        except Exception:
            used = _mem_get(key, bkt)
    else:
        used = _mem_get(key, bkt)

    rem = cap - used
    if rem < 0:
        rem = 0
    return rem
