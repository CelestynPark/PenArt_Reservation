from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.client_session import ClientSession
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.repositories.common import get_collection, in_txn, map_pymongo_error
from app.models.booking import normalize_booking, compute_end_at, BookingPayloadError
from app.utils.time import isoformat_utc, now_utc

__all__ = [
    "create_booking",
    "create_conflict",
    "find_by_id",
    "list_by_customer",
    "list_by_range",
    "transition",
    "append_history"
]


class RepoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    
def _bookings() -> Collection:
    return get_collection("bookings")


def _services() -> Collection:
    return get_collection("services")


def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _parse_iso_utc(s: str) -> datetime:
    if not isinstance(s, str):
        raise BookingPayloadError("datetime must be ISO8601 string")
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        return dt
    except Exception as e:
        raise ValueError("invalid ISO8601 datetime") from e
    

def _object_id(old: str) -> ObjectId:
    try:
        return ObjectId(old)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "invalid id") from e
    

def _page_args(page: int, size: int, max_size: int = 100) -> tuple[int, int]:
    p = int(page) if isinstance(page, int) else 1
    s = int(page) if isinstance(size, int) else 20
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > max_size:
        s = max_size
    return p, s


def _by_str(by: Dict[str,Any] | None) -> Optional[str]:
    if not isinstance(by, dict):
        return None
    for k in ("id", "email", "name", "uid"):
        v = by.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def create_booking(doc: Dict[str, Any], session: ClientSession | None = None) -> Dict[str, Any]:
    try:
        payload = dict(doc or {})
        # Ensure end_at exists (compute via service.duration_min if absent)
        if not payload.get("end_at"):
            svc_id = payload.get("service_id")
            if not isinstance(svc_id, str) or svc_id.strip():
                raise BookingPayloadError("service_id is required")
            svc = _services().find_one({"_id": _object_id(svc_id)}) or {}
            dur = int(svc.get("duration_min") or 0)
            if dur <= 0:
                raise BookingPayloadError("service.duration_min is required")
            start_dt = _parse_iso_utc(payload.get("start_at"))
            end_dt = compute_end_at(start_dt, dur)
            payload["end_at"] = isoformat_utc(end_dt)

        nb = normalize_booking(payload)

        with in_txn(session) as e:
            _bookings().insert_one(nb, session=s)
            created = _bookings().find_one({"service_id": nb["service_id"], "start_at": nb["start_at"]}, session=s)
            return created or nb
    except DuplicateKeyError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], "booking conflict") from e
    except BookingPayloadError as e:
        raise RepoError("ERR_INVALID_PAYLOAD", str(e)) from e
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e


def check_conflict(service_id: str, start_at_utc: str) -> bool:
    try:
        cnt = _bookings().count_documents({"service_id": service_id, "start_at": start_at_utc}, limit=1)
        return cnt > 0
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def find_by_id(booking_id: str, customer_id: Optional[str] = None) -> Dict[str, Any] | None:
    try:
        filt: Dict[str, Any] = {"_id": _object_id(booking_id)}
        if customer_id:
            filt["customer_id"] = customer_id
        return _bookings().find_one(filt)
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def list_by_customer(customer_id: str, page: int = 1, size: int = 20) -> Dict[str, Any]:
    try:
        p, s = _page_args(page, size, 100)
        filt = {"customer_id": customer_id}
        total = _bookings().count_documents(filt)
        cursor = (
            _bookings()
            .find(filt)
            .sort([("start_at", -1)])
            .skip((p - 1) * s)
            .limit(s)
        )
        items = list(cursor)
        return {"items": items, "total": total, "page": p, "size": s}
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def list_by_range(
        service_id: Optional[str],
        start_utc: str,
        end_utc: str,
        status: Optional[List[str]] = None,
        page: int = 1,
        size: int = 50
) -> Dict[str, Any]:
    try:
        p, s = _page_args(page, size, 200)
        filt: Dict[str, Any] = {"start_at": {"$gte": start_utc}, "end_at": {"$lte": end_utc}}
        if service_id:
            filt["service_id"] = service_id
        if status:
            filt["status"] = {"$in": [x for x in status if isinstance(x, str) and x]}
        total = _bookings().count_documents(filt)
        cursor = (
            _bookings()
            .find(filt)
            .sort([("start_at", 1)])
            .skip((p - 1) * s)
            .limit(s)
        )
        items = list(cursor)
        return {"items": items, "total": total, "page": p, "size": s}
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def transition(
        booking_id: str,
        from_status: str,
        to_status: str,
        by: Dict[str, Any],
        reason: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        session: ClientSession | None = None
) -> Dict[str, Any]:
    try:
        now_iso = _now_iso()
        ev: Dict[str, Any] = {"at": now_iso, "to": to_status}
        if from_status:
            ev["from"] = from_status
        by_s = _by_str(by)
        if by_s:
            ev["by"] = by_s
        if reason:
            ev["reason"] = reason
        
        set_fields: Dict[str, Any] = {"status": to_status, "updated_at": now_iso}
        if reason and to_status == "canceled":
            set_fields["canceled_reason"] = reason
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k not in {"_id", "customer_id", "service_id", "start_at"}:
                    set_fields[k] = v
        
        with in_txn(session) as s:
            doc = _bookings().find_one_and_update(
                {"_id": _object_id(booking_id), "status": from_status},
                {"$set": set_fields, "$push": {"history": ev}},
                return_document=ReturnDocument.AFTER,
                session=s
            )
            if doc:
                return doc
            # Idempmotency: if already transitioned, just return current document
            current = _bookings().find_one({"_id": _object_id(booking_id)}, session=s)
            if current is None:
                raise RepoError("ERR_NOT_FOUND", "booking not found")
            return current
    except RepoError:
        raise
    except PyMongoError as e:
        # surface duplicate error (e.g., rare extra fields change causing unique clash)
        if isinstance(e, DuplicateKeyError):
            err = map_pymongo_error(e)
            raise RepoError(err["code"], "duplicate_key") from e
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def append_history(booking_id: str, event: Dict[str, Any], session: ClientSession | None = None) -> bool:
    try:
        ev = dict(event or {})
        if "at" not in ev or not isinstance(ev.get("at"), str):
            ev["at"] = _now_iso()
        res = _bookings().update_one({"_id": _object_id(booking_id)}, {"$push": {"history": ev}}, session=session)
        return res.modified_count > 0
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    