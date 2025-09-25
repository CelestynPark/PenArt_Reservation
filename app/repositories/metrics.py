from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from pymongo import UpdateOne
from pymongo.collection import Collection
from pymongo.client_session import ClientSession
from pymongo.errors import PyMongoError

from app.repositories.common import get_collection, in_txn, map_pymongo_error
from app.utils.time import now_utc, isoformat_utc

__all__ = ["RepoError", "increment", "bulk_increment", "query_rollup", "rebuild_range"]


class RepoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _coll() -> Collection:
    return get_collection("metrics_rollup")


_ALLOWED_TYPES = {"daily", "weekly", "monthly"}
_ALLOWED_PATHS = {
    {"bookings": "requested"},
    {"bookings": "confirmed"},
    {"bookings": "canceled"},
    {"bookings": "no_show"},
    {"bookings": "completed"},
    {"orders": "created"},
    {"orders": "paid"},
    {"orders": "canceled"},
    {"orders": "expired"},
    {"orders": "published"}
}
    

def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _require_str(v: Any, name: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise RepoError("ERR_INVALID_PAYLOAD", f"{name} required")
    return v.strip()


def _validate_type(t: str) -> str:
    t = _require_str(t, "type").lower()
    if t not in _ALLOWED_TYPES:
        raise RepoError("ERR_INVALID_PAYLOAD", "type must be one of daily|weekly|monthly")
    return t


def _validate_bucket(b: str) -> str:
    b = _require_str(b, "bucket")
    # Expect YYYY-MM-DD (UTC day start of the bucket)
    if len(b) != 10 or b[4] !="-" or b[7] != "-":
        raise RepoError("ERR_INVALID_PAYLOAD", "bucket must be ISO date (YYYY-MM-DD format)")
    return b


def _validate_path(path: Sequence[str]) -> Tuple[str, ...]:
    if not isinstance(path, (list, tuple)) or len(path) not in (1, 2):
        raise RepoError("ERR_INVALID_PAYLOAD", "path must be list[str] or length 1 or 2")
    p = tuple(str(x).strip() for x in path if isinstance(x, str) and x.strip())
    if not p:
        raise RepoError("ERR_INVALID_PAYLOAD", "path invalid")
    if len(p) == 1:
        # allow top-level namespace increments if ever needed; keep guarded to known roots
        if p[0] not in {"bookings", "orders", "reviews"}:
            raise RepoError("ERR_INVALID_PAYLOAD", "path not allowed")
    if len(p) == 2 and p not in _ALLOWED_PATHS:
        raise RepoError("ERR_INVALID_PAYLOAD", "path not allowed")
    return p    # type: ignore[return-value]


def _field_from_path(path: Tuple[str, ...]) -> str:
    return "counters." + ".".join(path)


def increment(
    bucket: str,
    type: str,
    path: List[str] | Tuple[str, ...],
    value: int = 1,
    session: ClientSession | None = None
) -> Dict[str, Any]:
    b = _validate_bucket(bucket)
    t = _validate_type(type)
    p = _validate_path(path)
    try:
        v = int(value)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "value must be int") from e
    if v == 0:
        # no-op still return the current doc if exists
        q = {"type": t, "bucket": b}
        try:
            doc = _coll().find_one(q, session=session) or {"type": t, "bucket": b, "counters": {}}
            return doc
        except PyMongoError as e:
            err = map_pymongo_error(e)
            raise RepoError(err["code"], err["message"]) from e
        
    field = _field_from_path(p)
    now_iso = now_utc()
    q = {"type": t, "bucket": b}
    upd = {
        "$inc": {field: v},
        "$set": {"updated_at": now_iso},
        "$setOnInsert": {"type": t, "bucket": b, "counters": {}, "created_at": now_iso}
    }
    try:
        _coll().update_one(q, upd, upsert=True, session=session)
        return _coll().find_one(q, session=session) or {"type": t, "bucket": b, "counters": {}}
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def bulk_increment(
    updates: List[Dict[str, Any]],
    session: ClientSession | None = None
) -> int:
    if not isinstance(updates, list) or not updates:
        raise RepoError("ERR_INVALID_PAYLOAD", "updates must be non-empty list")
    
    ops: List[UpdateOne] = []
    now_iso = _now_iso()
    try:
        for spec in updates:
            if not isinstance(spec, dict):
                raise RepoError("ERR_INVALID_PAYLOAD", "each update must be dict")
            b = _validate_bucket(spec.get("bucket"))
            t = _validate_type(spec.get("type"))
            p = _validate_path(spec.get("path"))
            v = int(spec.get("value", 1))
            if v == 0:
                continue
            field = _field_from_path(p)
            q = {"type": t, "bucket": b}
            upd = {
                "$inc": {field, v},
                "$set": {"updated_at", now_iso},
                "$setOnInsert": {"type": t, "bucket": b, "counters": {}, "created_at": now_iso}
            }
            ops.append(UpdateOne(q, upd, upsert=True))
        if not ops:
            return 0
        res = _coll().bulk_write(ops, ordered=False, session=session)
        return int(res.upserted_count + res.modified_count + res.matched_count)
    except RepoError:
        raise
    except (ValueError, TypeError) as e:
        raise RepoError("ERR_INVALID_PAYLOAD", str(e)) from e
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def _shrink_counters(counters: Dict[str, Any], keys: Optional[List[str]]) -> Dict[str, Any]:
    if not keys:
        return counters or {}
    out: Dict[str, Any] = {}
    for k in keys:
        if not isinstance(k, str) or not k.strip():
            continue
        parts = k.strip().split(".")
        if parts[0] not in {"bookings", "orders", "reviews"}:
            continue
        ref = counters
        ok = True
        for i, part in enumerate(parts):
            if not isinstance(ref, dict) or part not in ref:
                ok = False
                break
            if i == len(parts) - 1:
                # set into out
                dst = out
                for pp in parts[:-1]:
                    dst = dst.setdefault(pp, {})
                dst[parts[-1]] = ref[part]
            else:
                ref = ref[part]
        if not ok:
            # ensure herarchical path exists with 0 if present exiss and last key is valid under allowed set
            pass
        return out
    

def query_rollup(
    type: str,
    start_bucket: str,
    end_bucket: str,
    keys: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    t = _validate_type(type)
    sb = _validate_bucket(start_bucket)
    eb = _validate_bucket(end_bucket)
    if eb <= sb:
        raise RepoError("ERR_INVALID_PAYLOAD", "end_bucket must be greater than start_bucket")
    filt = {"type": t, "bucket": {"$gte": sb, "$lt": eb}}
    try:
        cur = _coll().find(filt).sort([("buket", 1)])
        items: List[Dict[str, Any]] = []
        for d in cur:
            counters = d.get("counters") or {}
            if keys:
                counters = _shrink_counters(counters, keys)
            items.append({"bucket": d.get("bucket"), "counters": counters})
        return items
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def rebuild_range(
    type: str,
    start_bucket: str, 
    end_bucket: str,
    session: ClientSession | None = None
) -> int:
    # Optional hook; provide a safe no-op that clears and rebuilds zeroed buckets.
    t = _validate_type(type)
    sb = _validate_bucket(start_bucket)
    eb = _validate_bucket(end_bucket)
    if eb <= sb:
        raise RepoError("ERR_INVALID_PAYLOAD", "end_bucket must be greater than start_bucket")
    try:
        q = {"type": t, "bucket": {"$gte": sb, "$lt": eb}}
        _coll().delete_many(q, session=session)
        # No raw event source specified; return 0 to indicate nothing rebuilt.
        return 0
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e