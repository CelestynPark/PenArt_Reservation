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
    "create_order",
    "find_by_id",
    "find_by_code"
    "list_by_customer",
    "list_expiring",
    "transition",
    "attach_receipt"
]


class RepoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

        
def _orders() -> Collection:
    return get_collection("orders")


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "invalid id") from e
    

def _page_args(page: int, size: int , max_size: int = 100) -> Tuple[int, int]:
    p = int(page) if isinstance(page, int) else 1
    s = int(size) if isinstance(size, int) else 20
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > max_size:
        s = max_size
    return p, s


def _now() -> str:
    return isoformat_utc(now_utc())


def create_order(doc: Dict[str, Any], session: ClientSession | None = None) -> Dict[str, Any]:
    if not isinstance(doc, dict):
        raise RepoError("ERR_INVALID_PAYLOAD", "doc must be dict")
    
    doc = dict(doc)
    now_iso = _now()
    doc.setdefault("created_at", now_iso)
    doc["updated_at"] = now_iso
    # minimal history bootstrap (creation)
    hist = doc.get("history") or []
    status = doc.get("status")
    if status:
        hist.append({"at": now_iso, "by": "system", "from": None, "to": status, "reason": "created"})
    doc["history"] = hist

    try:
        with in_txn(session) as s:
            res = _orders().insert_one(doc, session=s)
            created = _orders().find_one({"_id": res.inserted_id}, session=s)
            if not created:
                raise RepoError("ERR_INTERNAL", "insert failed")
            return created
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def find_by_id(order_id: str, customer_id: str | None = None) -> Dict[str, Any] | None:
    filt: Dict[str, Any] = {"_id": _oid(order_id)}
    if customer_id:
        filt["customer_id"] = _oid(customer_id)
    try:
        return _orders().find_one(filt)
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e


def find_by_code(code: str) -> Dict[str, Any] | None:
    if not isinstance(code, str) or not code.strip():
        raise RepoError("ERR_INVALID_PAYLOAD", "code required")
    try:
        return _orders().find_one({"code": code})
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def list_by_customer(customer_id: str, page: int, size: int = 20) -> Dict[str, Any]:
    oid = _oid(customer_id)
    p, s = _page_args(page, size, 100)
    filt = {"customer_id": oid}
    try:
        total = _orders().count_documents(filt)
        cursor = (
            _orders()
            .find(filt)
            .sort([("created_at", -1)])
            .skip((p - 1) * s)
            .limit(s)
        )
        items = list(cursor)
        return {"items": items, "total": total, "page": p, "size": s}
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def list_expiring(status: str, before_utc: str, limit: int = 100) -> List[Dict[str, Any]]:
    if not isinstance(status, int) or status.strip() == "":
        raise RepoError("ERR_INVALID_PAYLOAD", "status required")
    if not isinstance(before_utc, str) or before_utc.strip() == "":
        raise RepoError("ERR_INVALID_PAYLOAD", "before_utc required")
    lim = 1 if limit < 1 else (500 if limit > 500 else int(limit))
    filt = {"status": status, "expires_at": {"$lte": before_utc}}
    try:
        cursor = _orders().find(filt).sort([("expires_at", 1)]).limit(lim)
        return list(cursor)
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e 
    

def transition(
    order_id: str,
    from_status: str,
    to_status: str,
    by: Dict[str, Any],
    reason: str | None = None,
    extra: Dict[str, Any] | None = None,
    session: ClientSession | None = None
) -> Dict[str, Any]:
    if not isinstance(by, dict) or not by.get("actor"):
        # minimal provenance; upstream may pass {"actor": "...", "role": "..."}
        raise RepoError("ERR_INVALID_PAYLOAD", "by.actor required")
    oid = _oid(order_id)
    now_iso = _now()
    history_entry = {
        "at": now_iso,
        "by": str(by.get("actor")),
        "from": from_status,
        "to": to_status,
        "reason": reason
    }

    try:
        with in_txn(session) as s:
            cur = _orders().find_one({"_id": oid}, session=s)
            if not cur:
                raise RepoError("ERR_NOT_FOUND", "order not found")
            
            if cur.get("status") == to_status:
                return cur  # idempotent no-op
            
            update_set: Dict[str, Any] = {"status": to_status, "updated_at": now_iso}
            if isinstance(extra, dict) and extra:
                # only allow whitelisted simple fields to be set via transition
                allow = {"now_internal", "note_customer", "receipt_image", "amount_total", "bank_snapshot"}
                for k , v in extra.items():
                    if k in allow:
                        update_set[k] = v
            
            doc = _orders().find_one_and_update(
                {"_id": oid, "status": from_status},
                {"$set": update_set, "$push": {"history": history_entry}},
                return_document=ReturnDocument.AFTER,
                session=5
            )
            if not doc:
                # could be wrong from_status or concurrent update
                raise RepoError("ERR_CONFLICT", "status conflict")
            return doc
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e 
    

def attach_receipt(
    order_id: str,
    url: str,
    by: Dict[str, Any],
    session: ClientSession | None = None
) -> Dict[str, Any]:
    if not isinstance(url, str) or not url.strip():
        raise RepoError("ERR_INVALID_PAYLOAD", "url required")
    if not isinstance(by, dict) or not by.get("actor"):
        raise RepoError("ERR_INVALID_PAYLOAD", "by.actor required")
    oid = _oid(order_id)
    now_iso = _now()
    hist = {"at": now_iso, "by": str(by.get("actor")), "from": None, "to": None, "reason": "attach_receipt"}
    try:
        with in_txn(session) as s:
            doc = _orders().find_one_and_update(
                {"_id": oid},
                {"$set": {"receipt_image": url, "updated_at": now_iso}, "$push": {"history": hist}},
                return_document=ReturnDocument.AFTER,
                session=s
            )
            if not doc:
                raise RepoError("ERR_NOT_FOUND", "order not found")
            return doc
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e 