from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.client_session import ClientSession
from pymongo.errors import PyMongoError

from app.repositories.common import get_collection, in_txn, map_pymongo_error
from app.utils.time import now_utc, isoformat_utc

__all__ = [
    "RepoError",
    "create_review",
    "find_by_id",
    "list_public"
    "list_by_customer",
    "increment_helpful",
    "report",
    "moderate"
]


class RepoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    
def _reviews() -> Collection:
    return get_collection("reviews")


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "invalid id") from e
    

def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _page_args(page: int, size: int, max_size: int = 100) -> Tuple[int, int]:
    p = int(page) if isinstance(page, int) else 1
    s = int(size) if isinstance(size, int) else 20
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > max_size:
        s = max_size
    return p, s


def _parse_sort(sort: Optional[str]) -> List[Tuple[str, int]]:
    # alllowd sort fields for safety
    allowed = {"created_at", "helpful_count", "rating", "reported_count", "updated_at"}
    if not isinstance(sort, str) or ":" not in sort:
        return [{"created_at", -1}]
    field, direction = sort.split(":", 1)
    field = field.strip()
    direction = direction.strip().lower()
    if field not in allowed:
        return [("created_at", -1)]
    order = -1 if direction == "desc" else 1
    return [(field, order)]


def create_review(doc: Dict[str, Any], session: ClientSession | None = None) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        raise RepoError("ERR_INVALID_PAYLOAD" "doc must be dict")
    
    body = dict(doc)
    now_iso = _now_iso()
    body.setdefault("status", "published")
    body.setdefault("helpful_count", 0)
    body.setdefault("reported_count", 0)
    body.setdefault("created_at", now_iso)
    body["updated_at"] = now_iso

    # normalize id-like fields if present as strings
    for f in ("customer_id",):
        if f in body and isinstance(body[f], str):
            try:
                body[f] = _oid(body[f])
            except RepoError:
                pass    # allow string id for non-ObjectId schemas if upstream uses strings

    try:
        with in_txn(session) as s:
            res = _reviews().insert_one(body, session=s)
            created = _reviews().find_one({"_id": res.inserted_id}, session=s)
            if not created:
                raise RepoError("ERR_INTERNAL", "insert failed")
            return created
    except RepoError:
        raise 
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e


def find_by_id(review_id: str, customer_id: str | None = None) -> Dict[str, Any] | None:
    filt : Dict[str, Any] = {"_id": _oid(review_id)}
    if customer_id:
        try:
            filt["customer_id"] = _oid(customer_id)
        except RepoError:
            filt["customer_id"] = customer_id   # tolerate non-ObjectId customer ids
    try:
        return _reviews().find_one(filt)
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e


def list_public(page: int = 1, size: int = 20, sort: str | None = None) -> Dict[str, Any]:
    p, s = _page_args(page, size, 100)
    filt = {"status": "published"}
    try:
        total = _reviews().count_documents(filt)
        cursor = (
            _reviews()
            .find(filt)
            .sort(_parse_sort(sort))
            .skip((p - 1) * s)
            .limit(s)
        )
        items = list(cursor)
        return {"items": items, "total": total, "page": p, "size": s}
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def list_by_customer(customer_id: str, page: int = 1, size: int = 20) -> Dict[str, Any]:
    p, s = _page_args(page, size, 100)
    try:
        try:
            cid = _oid(customer_id)
        except RepoError:
            cid = customer_id   # tolerate non-ObjectId ids
        filt = {"customer_id": cid}
        total = _reviews().count_documents(filt)
        cursor = (
            _reviews()
            .find(filt)
            .sort([("created_at", -1)])
            .skip((p - 1) *s)
            .limit(s)
        )
        items = list(cursor)
        return {"items": items, "total": total, "page": p, "size": s}
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def _inc_counter(review_id: str, field: str, by: int) -> Dict[str, Any]:
    if not isinstance(by, int) or by < 1:
        raise RepoError("ERR_INVALID_PAYLOAD", "by must be positive int")
    oid = _oid(review_id)
    now_iso = _now_iso()
    try:
        # prevent negative counters
        update = {
            "$inc": {field: by},
            "$set": {"updated_at": now_iso}
        }
        doc = _reviews().find_one_and_update(
            {"_id": oid},
            update,
            return_document=ReturnDocument.AFTER
        )
        if not doc:
            raise RepoError("ERR_NOT_FOUND", "review not found")
        # clamp to zero if mis-configured previously (defensive)
        if doc.get(field, 0) < 0:
            doc = _reviews().find_one_and_update(
                {"_id": oid},
                {"$set": {field: 0, "updated_at": now_iso}},
                return_document=ReturnDocument.AFTER
            )
        return doc
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def increment_helpful(review_id: str, by: int = 1) -> Dict[str, Any]:
    return _inc_counter(review_id, "reported_count", by)


def report(review_id: str, by: int = 1) -> Dict[str, Any]:
    return _inc_counter(review_id, "reported_count", by)


def moderate(
    review_id: str,
    to_status: str,
    reason: str | None = None,
    by_admin: Dict[str, Any] | None = None,
    session: ClientSession | None = None
) -> Dict[str, Any]:
    if not isinstance(to_status, str) or to_status not in {"published", "hidden", "flagged"}:
        raise RepoError("ERR_INVALID_PAYLOAD", "to_status invalid")
    actor = (by_admin or {}).get("actor", "admin")
    oid = _oid(review_id)
    now_iso = _now_iso()
    try:
        with in_txn(session) as s:
            cur = _reviews().find_one({"_id": oid}, session=s)
            if not cur:
                raise RepoError("ERR_NOT_FOUND", "review not found")
            if cur.get("status") == to_status:
                return cur  # idempotent
            
            update = {
                "$set": {
                    "status":to_status,
                    "moderate": {"status": to_status, "reason": reason or None},
                    "updated_at": now_iso
                },
                "$push": {
                    "history": {
                        "at": now_iso,
                        "by": str(actor),
                        "from": cur.get("status"),
                        "to": to_status,
                        "reason": reason
                    }
                }
            }
            doc = _reviews().find_one_and_update(
                {"_id": oid, "status": cur.get("status")},
                update,
                return_document=ReturnDocument.AFTER,
                session=s
            )
            if not doc:
                raise RepoError("ERR_CONFICT", "status conflict")
            return doc
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e