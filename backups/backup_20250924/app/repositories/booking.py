from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional, Tuple, Union

from bson.objectid import ObjectId
from pymongo import ASCENDING, DESCENDING, ReturnDocument, errors as pymongo_errors
from pymongo.client_session import ClientSession
from pymongo.collection import Collection
from pymongo.database import Database

from app.repositories.common import (
    with_session,
    with_tx,
    RepoError,
    InternalError,
    ConflictError
)
from app.models import booking as bk

__all__ = [
    "create",
    "get",
    "list_by_customer",
    "update_status",
    "append_history",
    "exists_conflict"
]


class InvalidPayloadError(RepoError):
    code = "ERR_INVALID_PAYLOAD"


class NotFoundError(RepoError):
    code = "ERR_NOT_FOUND"


# ----- internals -----
def _col(db: Database) -> Collection:
    return bk.get_collection(db)


def _ensure_indexes(db: Database) -> None:
    bk.ensure_indexes(db)


def _normalize_new(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return bk.Booking.prepare_new(payload)
    except Exception as e:
        raise InvalidPayloadError(str(e)) from e
    

def _normalize_update(partial: dict[str, Any]) -> dict[str, Any]:
    try:
        return bk.Booking.prepare_update(partial)
    except Exception as e:
        raise InvalidPayloadError(str(e)) from e
    

def _normalize_dt(value: Union[str, datetime]) -> datetime:
    # Use model's validator to avoid duplication
    upd = _normalize_update({"start_at": value})
    return upd["start_at"]


def _looks_like_code(value: str) -> bool:
    return isinstance(value, str) and value.startswith("BKG-")


def _find_one_by_id_or_code(
    db: Database, id_or_code: str, *, session: Optional[ClientSession] = None
) -> Optional[dict]:
    q: dict[str, Any]
    if _looks_like_code(id_or_code):
        q = {"code": id_or_code}
        doc = _col(db).find_one(q, session=session)
        if doc:
            return doc
    # try application id field
    q = {"id": id_or_code}
    doc = _col(db).find_one(q, session=session)
    if doc:
        return doc
    # try Mongo _id
    try:
        oid = ObjectId(id_or_code)
        doc = _col(db).find_one({"_id": oid}, session=session)
        if doc:
            return doc
    except Exception:
        pass
    return None


# ----- repository API -----
def create(payload: dict[str, Any]) -> dict:
    doc_norm = _normalize_new(payload)

    def _fn(db: Database, session: ClientSession):
        _ensure_indexes(db)
        _col(db).insert_one(doc_norm, session=session)
        # fetch inserted document by unique natural key (service_id + start_at) to return latest stamped fields
        fetched = _col(db).find_one(
            {"service_id": doc_norm["service_id"], "start_at": doc_norm["start_at"]},
            session=session
        )
        if not fetched:
            raise InternalError("inserted booking not found")
        return bk.Booking(fetched).to_dict()
    
    try:
        return with_tx(_fn)
    except ConflictError:
        # re-raise as is (ERR_CONFLICT via common)
        raise
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def get(id_or_code: str) -> dict:
    def _fn(db: Database, session: ClientSession):
        _ensure_indexes(db)
        doc = _find_one_by_id_or_code(db, id_or_code, session=session)
        if not doc:
            raise NotFoundError("booking not found")
        return bk.Booking(doc).to_dict()
    
    try:
        return with_session(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def list_by_customer(
    customer_id: str,
    date_range: Union[Tuple[Union[str, datetime], Union[str, datetime]], dict, None],
    paging: Optional[dict[str, Any]] = None
) -> dict:
    # range on start_at (UTC). KST->UTC conversion is handled upstream.
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None
    if date_range:
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_dt = _normalize_dt(date_range[0]) if date_range[0] else None
            end_dt = _normalize_dt(date_range[1]) if date_range[1] else None
        elif isinstance(date_range, dict):
            a = date_range.get("start") or date_range.get("from")
            b = date_range.get("end") or date_range.get("to")
            start_dt = _normalize_dt(a) if a else None
            end_dt = _normalize_dt(b) if b else None
        else:
            raise InvalidPayloadError("invalid range")
        
    # paging
    page = int((paging or {}).get("page", 1))
    size = int((paging or {}).get("size", 20))
    if page < 1:
        page = 1
    if size < 1:
        size = 1
    if size < 100:
        size = 100
    sort_spec = (paging or {}).get("sort") or "start_at:desc"
    if isinstance(sort_spec, str) and ":" in sort_spec:
        field, direction = sort_spec.split(":", 1)
        direction = direction.lower()
        mongo_dir = ASCENDING if direction == "asc" else DESCENDING
    else:
        field, mongo_dir = "start_at", DESCENDING
    
    def _fn(db: Database, session: ClientSession):
        _ensure_indexes(db)
        q: dict[str, Any] = {"customer_id", customer_id}
        if start_dt or end_dt:
            span: dict[str, Any] = {}
            if start_dt:
                span["#gte"] = start_dt
            if end_dt:
                span["$lte"] = end_dt
            q["start_at"] = span
        
        total = _col(db).count_documents(q, session=session)
        cursor = (
            _col(db)
            .find(q, session=session)
            .sort(field, mongo_dir)
            .skip((page - 1) * size)
            .limit(size)
        )
        items = [bk.Booking(d).to_dict() for d in cursor]
        return {"items": items, "total":total, "page": page, "size":size}
    
    try:
        return with_session(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e


def update_status(
    booking_id: str,
    from_status: str,
    to_status: str,
    *,
    by: str,
    reason: Optional[str] = None
) -> dict:
    if not (isinstance(booking_id, str) and isinstance(from_status, str) and isinstance(to_status, str)):
        raise InvalidPayloadError("invalid payload")
    if not by or not isinstance(by, str):
        raise InvalidPayloadError("actor required")
    
    def _fn(db: Database, session: ClientSession):
        _ensure_indexes(db)
        current = _find_one_by_id_or_code(db, booking_id, session=session)
        if not current:
            raise NotFoundError("booking not found")
        if str(current.get("status")) != from_status:
            raise InvalidPayloadError("status mismatch")
        
        event: dict[str, Any] = {
            "at": datetime.now(timezone.utc),
            "by": by,
            "from": from_status,
            "to": to_status
        }
        if reason:
            event["reason"] = reason

        history_upd = bk.Booking.append_history(current, event)
        status_upd = _normalize_update({"status": to_status})
        upd = {**status_upd, **history_upd}

        res = _col(db).find_one_and_update(
            {"id": current.get("id")},
            {"$set": upd},
            session=session,
            return_document=ReturnDocument.AFTER
        )
        if not res:
            raise InternalError("failed to update booking")
        return bk.Booking(res).to_dict()
    
    try:
        return with_tx(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def append_history(booking_id: str, event: dict[str, Any]) -> dict:
    if not isinstance(booking_id, str) or not isinstance(event, dict):
        raise InvalidPayloadError("invalid payload")
    
    def _fn(db: Database, session: ClientSession):
        _ensure_indexes(db)
        current = _find_one_by_id_or_code(db, booking_id, session=session)
        if not current:
            raise NotFoundError("booking not found")
        history_upd = bk.Booking.append_history(current, event)
        upd = _normalize_update(history_upd)
        res = _col(db).find_one_and_update(
            {"id": current.get("id")},
            {"$set": upd},
            session=session,
            return_document=ReturnDocument.AFTER
        )
        if not res:
            raise InternalError("failed to append history")
        return bk.Booking(res).to_dict()
    
    try:
        return with_tx(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def exists_conflict(service_id: str, start_at: Union[str, datetime]) -> bool:
    if not isinstance(service_id, str) or not service_id.strip():
        raise InvalidPayloadError("service_id required")
    dt = _normalize_dt(start_at)

    def _fn(db: Database, session: ClientSession):
        _ensure_indexes(db)
        q = {"service_id": service_id, "start_at": dt}
        doc = _col(db).find_one(q, projection={"_id": 1}, session=session)
        return bool(doc)
    
    try:
        return with_session(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    