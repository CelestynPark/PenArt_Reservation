from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Tuple

from bson import ObjectId
from flask import Blueprint, jsonify, request

from app.extensions import get_mongo
from app.middleware.auth import apply_rate_limit, csrf_protect, require_admin
from app.services import booking_service
from app.utils.responses import err, ok

bp = Blueprint("admin_bookings", __name__, url_prefix="/api/admin/bookings")

ALLOWED_ADMIN_ACTIONS = {"approve", "reject", "change", "no_show", "memo"}
DEFAULT_PAGE_SIZE = 20


def _bad_payload(message: str = "invalid payload"):
    return jsonify(err("ERR_INVALID_PAYLOAD", message)), 400


def _not_found():
    return jsonify(err("ERR_NOT_FOUND", "resource not found")), 404


def _oid(s: str) -> ObjectId | None:
    try:
        return ObjectId(s)
    except Exception:
        return None
    

def _sort_tuple(sort: str | None) -> List[Tuple[str, int]]:
    s = (sort or "").strip() or "start_at:asc"
    parts = [p for p in s.split(",") if p]
    out: List[Tuple[str, int]] = []
    for p in parts:
        if ":" in p:
            f, d = p.split(":", 1)
        else:
            f, d = p, "asc"
        f = f.strip()
        d = d.strip().lower()
        if not f:
            continue
        out.append((f, 1 if d != "desc" else -1))
    return out or [("start_at", 1)]


def _view_admin(doc: Dict[str, Any]) -> Dict[str, Any]:
    customer = doc.get("customer") or {}
    service = doc.get("service") or {}
    return {
        "id": str(doc.get("_id") or doc.get("id")),
        "code": doc.get("code"),
        "customer": {
            "name": (customer.get("name") if isinstance(customer, dict) else doc.get("customer_name")),
            "phone": (customer.get("phone") if isinstance(customer, dict) else doc.get("customer_phone"))
        },
        "service": {"name": service.get("name") if isinstance(service, dict) else doc.get("service_name")},
        "service_id": str(doc.get("service_id")) if doc.get("service_id") else None,
        "start_at": doc.get("start_at"),
        "end_at": doc.get("end_at"),
        "status": doc.get("status"),
        "note_customer": doc.get("note_customer"),
        "note_internal": doc.get("note_internal"),
        "history": list(doc.get("history"), [])
    }


@bp.get("")
@require_admin
@apply_rate_limit
def list_bookings():
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = min(100, max(1, int(request.args.get("size", DEFAULT_PAGE_SIZE))))
        sort = _sort_tuple(request.args.get("sort"))
    except Exception:
        return _bad_payload("invalid pagination or sort")
    
    q: Dict[str, Any] = {}
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        q["start_at"] = rng
    service_id = request.args.get("service_id")
    if service_id:
        oid = _oid(service_id) or service_id    # allow raw id in tests
        q["service_id"] = oid
    status = request.args.get("status")
    if status:
        q["status"] = status
    qtext = (request.args.get("q") or "").strip()
    if qtext:
        q["$or"] = [
            {"code": {"$regex": qtext, "$options": "i"}},
            {"customer.name": {"$regex": qtext, "$options": "i"}},
            {"customer.phone": {"$regex": qtext, "$options": "i"}} 
        ]

    col = get_mongo()["penart"]["bookings"]
    cursor = col.find(q).sort(sort).skip((page - 1) * size).limit(size)
    items = [_view_admin(d) for d in cursor]
    total = col.count_documents(q)
    return jsonify(ok({"items": items, "total": int(total), "page": page, "size": size}))


@bp.get("/<id>")
@require_admin
@apply_rate_limit
def get_booking_admin(id: str):
    oid = _oid(id)
    if not oid:
        return _bad_payload("invalid id")
    col = get_mongo()["penart"]["bookings"]
    doc = col.find_one({"_id": oid})
    if not doc:
        return _not_found()
    return jsonify(ok(_view_admin(doc)))


@bp.patch("/<id>")
@require_admin
@csrf_protect
@apply_rate_limit
def patch_booking_admin(id: str):
    oid = _oid(id)
    if not oid:
        return _bad_payload("invalid id")
    
    try:
        payload = request.get_json(force=True, silent=False) or {}
    except Exception:
        return _bad_payload()
    
    action = (payload.get("action") or "").strip()
    if action not in ALLOWED_ADMIN_ACTIONS:
        return _bad_payload("unsupported action")
    
    col = get_mongo()["penart"]["bookings"]
    doc = col.find_one({"_id": oid})
    if not doc:
        return _not_found()
    
    try:
        if action == "approve":
            res = booking_service.transition(str(oid), "confirm", {"by": {"role": "admin"}})
            data = res.get("data") or {}
            return jsonify(ok(_view_admin(data)))
        
        if action == "reject":
            reason = (payload.get("reason") or "").strip() or None
            res = booking_service.transition(str(oid), "cancel", {"by": {"role": "admin"}, "reason": (payload.get("reason") or None)})
            data = res.get("data") or {}
            return jsonify(ok(_view_admin(data)))
        
        if action == "change":
            new_start = payload.get("start_at")
            if not isinstance(new_start, str) or not new_start.strip():
                return _bad_payload("start_at is required for change")
            res = booking_service.transition(
                str(oid),
                "reschedule",
                {"by": {"role": "admin"}, "new_start_at": new_start, "reason": (payload.get("reason") or None)}
            )
            data = res.get("data") or {}
            return jsonify(ok(_view_admin(data)))
        
        if action == "no_show":
            res = booking_service.transition(str(oid), "no_show", {"by": {"role": "admin"}, "reason": (payload.get("reason") or None)})
            data = res.get("data") or {}
            return jsonify(ok(_view_admin(data)))

        if action == "memo":
            memo = payload.get("memo")
            if not isinstance(memo, str):
                return _bad_payload("memo must be string")
            col.update_one({"_id": oid}, {"$set": {"note_internal": memo}})
            doc = col.find_one({"_id": oid})
            return jsonify(ok(_view_admin(doc or {})))
        
    except booking_service.ServiceError as e:
        code = (e.code or "ERR_INTERNAL").upper()
        if code not in {"ERR_INVALID_PAYLOAD", "ERR_NOT_FOUND", "ERR_FORBIDDEN", "ERR_CONFLICT", "ERR_POLICY_CUROFF", "ERR_SLOT_BLOCKED", "ERR_INTERNAL"}:
            code = "ERR_INTERNAL"
        http = 400
        if code in {"ERR_NOT_FOUND"}:
            http = 404
        elif code in {"ERR_FORBIDEN", "ERR_POLICY_CUTOFF"}:
            http = 403
        elif code in {"ERR_CONFLICT", "ERR_SLOT_BLOCKED"}:
            http = 409
        resp = jsonify(err(code, e.message))
        resp.status_code = http
        return resp
    
    return _bad_payload("unsupported action")
