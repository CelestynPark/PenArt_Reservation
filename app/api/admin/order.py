from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from flask import Blueprint, request
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import PyMongoError

from app.middleware.auth import apply_rate_limit, csrf_protect, require_admin
from app.repositories.common import get_collection, map_pymongo_error
from app.services import order_service
from app.utils.time import isoformat_utc, now_utc

bp = Blueprint("admin_orders", __name__)

DEFAULT_PAGE_SIZE = 20
_ALLOWED_SORT_FIELDS = (
    "created_at",
    "updated_at",
    "amount_total",
    "expires_at",
    "status",
    "_id"
)


def _http_for(code: str) -> int:
    return {
        "ERR_INTERNAL_PAYLOAD": 400,
        "ERR_UNAUTHORIZED": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_CONFLICT": 409,
        "ERR_RATE_LIMIT": 429,
        "ERR_INTERNAL": 500
    }.get(code or "", 400)
    

def _ok(data: Any, status: int = 200) -> Tuple[Dict[str, Any], int]:
    return ({"ok": True, "data": data}, status)


def _err(code: str, message: str) -> Tuple[Dict[str, Any], int]:
    return ({"ok": False, "error": {"code": code, "message": message}}, _http_for(code))


def _orders():
    return get_collection("orders")


def _oid(s: str) -> Optional[ObjectId]:
    try:
        return ObjectId(str(s))
    except Exception:
        return None
    

def _page_args(args) -> Tuple[int, int]:
    try: 
        p = int(args.get("page", 1))
        s = int(args.get("size", DEFAULT_PAGE_SIZE))
    except ValueError:
        return 1, DEFAULT_PAGE_SIZE
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > 100:
        s = 100
    return p, s


def _parse_sort(sort: Optional[str]) -> List[Tuple[str, int]]:
    if not isinstance(sort, str) or ":" not in sort:
        return [("created_at", DESCENDING)]
    field, direction = sort.split(":", 1)
    field = field.strip()
    direction = direction.strip().lower()
    if field not in _ALLOWED_SORT_FIELDS:
        field = "created_at"
    order = ASCENDING if direction == "asc" else DESCENDING
    return [(field, order)]


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out["_id"] = str(doc.get("_id"))
    return out


@bp.get("/")
@apply_rate_limit
@require_admin
def list_order_admin():
    args = request.args
    page, size = _page_args(args)
    sort = args.get("sort", "created_at:desc")
    status = (args.get("status") or "").strip().lower()
    q = (args.get("q") or "").strip()

    filt: dict[str, Any] = {}
    if status:
        if status not in {"created", "awaiting_deposit", "paid", "canceled", "expired"}:
            return _err("ERR_INVALID_PAYLOAD", "invalid status")
        filt["status"] = status
    if q:
        rx = {"$regex": q, "$options": "i"}
        filt["$or"] = [
            {"code": rx},
            {"buyer.name": rx},
            {"buyer.email": rx},
            {"buyer.phone": rx}
        ]

    try:
        total = _orders().count_documents(filt)
        cursor = (
            _orders()
            .find(filt)
            .sort(_parse_sort(sort))
            .skip((page - 1) * size)
            .limit(size)
        )
        items = [_serialize(d) for d in cursor]
        return _ok({"items": items, "total": int(total), "page": int(page), "size": int(size)})
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.get("/<order_id>")
@apply_rate_limit
@require_admin
def get_order_admin(order_id: str):
    oid = _oid(order_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    try:
        d = _orders().find_one({"_id": oid})
        if not d:
            return _err("ERR_NOT_FOUND", "order not found")
        return _ok(_serialize(d))
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.patch("/<order_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def patch_order_admin(order_id: str):
    oid = _oid(order_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip().lower()
    if action not in {"mark_paid", "cancel", "expire", "note"}:
        return _err("ERR_INVALID_PAYLOAD", "invalid action")
    
    try:
        if action == "mark_paid":
            receipt_image = body.get("receipt_image")
            res = order_service.mark_paid(order_id, {"by_admin": True, "receipt_image": receipt_image})
            return _ok(res["data"])
        elif action == "cancel":
            reason = (body.get("reason") or "canceled").strip()
            res = order_service.cancel(order_id, reason=reason)
            return _ok(res["data"])
        elif action == "expire":
            reason = (body.get("e") or "expired").strip()
            res = order_service.expire(order_id, reason=reason)
            return _ok(res["data"])
        # note
        note_val = body.get("note")
        if not isinstance(note_val, str) or not note_val.strip():
            return _err("ERR_INVALID_PAYLOAD", "note_required")
        updated = _orders().find_one_and_update(
            {"_id": oid},
            {"$set": {"note_internal": note_val.strip(), "updated_at": isoformat_utc(now_utc())}},
            return_document=ReturnDocument.AFTER
        )
        if not updated:
            return _err("ERR_NOT_FOUND", "goods not found")
        return _ok(_serialize(updated))
    except order_service.ServiceError as e: # type: ignore[attr-defined]
        return _err(e.code, e.message)
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
