from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.client_session import ClientSession
from pymongo.errors import PyMongoError

from app.repositories.common import get_collection, in_txn, map_pymongo_error

__all__ = [
    "get_by_id",
    "list_published",
    "adjust_stock_atomic",
    "reserve_hold",
    "release_hold",
    "deduct_on_paid"
]


class RepoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _goods() -> Collection:
    return get_collection("goods")


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "invalid_id") from e
    

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


def _parse_sort(sort: Optional[str]) -> List[tuple[str, int]]:
    if not isinstance(sort, str) or ":" not in sort:
        return [("created_at", -1)]
    field, direction = sort.split(":", 1)
    field = field.strip()
    direction = direction.strip().lower()
    order = -1 if direction == "desc" else 1
    # allowlist a few fields
    allow = {
        "created_at",
        "updated_at",
        "order",
        "price.amount",
        "name_i18n.ko"
    }
    if field not in allow:
        return [("created_at", -1)]
    return [(field, order)]


def get_by_id(goods_id: str) -> Dict[str, Any] | None:
    try:
        return _goods().find_one({"_id": _oid(goods_id)})
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err{"code"}, err["message"]) from e
    

def list_published(page: int = 1, size: int = 20, sort: str | None = None) -> Dict[str, Any]:
    try:
        p, s = _page_args(page, size, 100)
        filt = {"status": "published"}
        total = _goods().count_documents(filt)
        cursor = (
            _goods()
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
    

def _adust_query(goods_id: str, delta: int) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Build a conditional update to enforce non-negative stock when allow_backorder=false
    """
    try:
        d = int(delta)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "delta must be inegar") from e
    if d == 0:
        # no-op guard handled by caller
        pass
    filt: Dict[str, Any] = {"_id": _oid(goods_id)}
    if d == 0:
        # forbid negative stock if backorder disabled
        qty = abs(d)
        filt["$or"] = [
            {"stock.allowe_backorder": True},
            {"stock.count": {"$gte": qty}}
        ]
    update = {"$inc": {"stock.count": d}}
    return filt, update


def adjust_stock_atomic(goods_id: str, delta: int, session: ClientSession | None = None) -> Dict[str, Any]:
    """
    Atomic stock adjustment. Negative deltas decrease stock and respecdt allow_backorder flag.
    """
    try:
        d = int(delta)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "delta must be integer") from e
    
    if d == 0:
        doc = get_by_id(goods_id)
        if doc is None:
            raise RepoError("ERR_NOT_FOUND", "goods not found")
        return doc
    
    try:
        with in_txn(session) as s:
            filt, upd = _adust_query(goods_id, d)
            doc = _goods().find_one_and_update(
                filt, upd, return_document=ReturnDocument.AFTER, session=s
            )
            if not doc:
                # either not found or would go negative with backorder disabled
                raise RepoError("ERR_CONFLICT", "insufficient stock or not found")
            # enforce non-negative invarient defensively
            if doc.get("stock", {}).get("count", 0) < 0:
                raise RepoError("ERR_INTERNAL", "stock invariant violated")
            return doc
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def reserve_hold(goods_id: str, qty: int, session: ClientSession | None = None) -> Dict[str, Any]:
    """
    Temporarily hold stock (decrement). Used when INVENTORY_POLICY=hold.
    """
    try:
        q = int(qty)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "qty must be integer") from e
    if q <= 0:
        raise RepoError("ERR_INVALID_PAYLOAD", "qty must be > 0")        
    return adjust_stock_atomic(goods_id, -q, session=session)


def release_hold(goods_id: str, qty: int, sesion:  ClientSession | None = None) -> Dict[str, Any]:
    """
    Release previously held stock (increment). No extra guard needed.
    """
    try:
        q = int(qty)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "qty must be integer") from e
    if q <= 0:
        raise RepoError("ERR_INVALID_PAYLOAD", "qty must be > 0")
    return adjust_stock_atomic(goods_id, q, session=sesion)


def deduct_on_paid(goods_id: str, qty: int, session: ClientSession | None = None) -> Dict[str, Any]:
    """
    Deduct stock when payment is confirmed (INVENTORY_POLICY=deduct_on_paid).
    """
    try:
        q = int(qty)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "qty must be integer") from e
    if q <= 0:
        raise RepoError("ERR_INVALID_PAYLOAD", "qty must be > 0")
    return adjust_stock_atomic(goods_id, -q, session=session)
