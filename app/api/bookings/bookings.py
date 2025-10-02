from __future__ import annotations

from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, g

from app.utils.responses import ok, err
from app.core.constants import ErrorCode
from app.services import booking_service as svc
from app.repositories import booking as booking_repo

bp = Blueprint("bookings", __name__, url_prefix="/api/bookings")


# ----------- helpers -----------

_STATUS_MAP = {
    ErrorCode.ERR_INVALID_PAYLOAD.value: 400,
    ErrorCode.ERR_UNAUTHORIZED.value: 401,
    ErrorCode.ERR_FORBIDDEN.value: 403,
    ErrorCode.ERR_NOT_FOUND.value: 404,
    ErrorCode.ERR_CONFLICT.value: 409,
    ErrorCode.ERR_POLICY_CUTOFF.value: 409,
    ErrorCode.ERR_SLOT_BLOCKED.value: 409,
    ErrorCode.ERR_INTERNAL.value: 500
}


def _json_error(code: str, message: str):
    status = _STATUS_MAP.get(code, 400)
    return jsonify(err(code, message)), status


def _current_user_id() -> Optional[str]:
    if hasattr(g, "user") and isinstance(getattr(g, "user"), dict):
        return g.user.get("id")
    return getattr(g, "user_id", None)


def _assert_owner(b: Dict[str, Any]) -> Optional[Any]:
    uid = _current_user_id()
    owner = b.get("customer_id")
    if owner and uid and str(owner) != str(uid):
        return _json_error(ErrorCode.ERR_FORBIDDEN.value, "forbidden")
    return None


def _public_fields(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc.get("_id") or doc.get("id")),
        "code": doc.get("code"),
        "status": doc.get("status"),
        "start_at": doc.get("start_at"),
        "end_at": doc.get("end_at")
    }


# ----------- routes -----------

@bp.post("")
def create_booking():
    try:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "invalid json")
        
        # Basic required fields (deep validation inside service)
        for f in ("service_id", "start_at", "name", "phone", "agree"):
            if f not in payload:
                return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, f"missing field: {f}")
            
        res = svc.create_request(payload)
        if res.get("ok") is not True:
            e = res.get("error") or {}
            return _json_error(e.get("code") or ErrorCode.ERR_INTERNAL.value, e.get("message") or "failed")
        
        data = res.get("data") or {}
        return jsonify(ok(_public_fields(data)))
    except svc.ServiceError as e:
        return _json_error(e.code, e.message)
    except Exception:
        return _json_error(ErrorCode.ERR_INTERNAL.value, "internal error")
    

@bp.get("/<booking_id>")
def get_booking(booking_id: str):
    try:
        b = booking_repo.find_by_id(booking_id)
        if not b:
            return _json_error(ErrorCode.ERR_NOT_FOUND.value, "booking not found")
        
        owner_err = _assert_owner(b)
        if owner_err:
            return owner_err
        
        return jsonify(ok(_public_fields(b)))
    except Exception:
        return _json_error(ErrorCode.ERR_INTERNAL.value, "internal error")
    

@bp.patch("/<booking_id>")
def patch_booking(booking_id: str):
    try:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "invalid json")
        
        action = (payload.get("action") or "").strip().lower()
        if not action:
            return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "action is required")
        
        # Fetch for permission checks
        b = booking_repo.find_by_id(booking_id)
        if not b:
            return _json_error(ErrorCode.ERR_NOT_FOUND.value, "booking not found")
        
        owner_err = _assert_owner(b)
        if owner_err:
            return owner_err
        
        # Map pubilc actions to service actions/meta
        meta: Dict[str, Any] = {"by": {"user_id": _current_user_id()}}
        if action == "cancel":
            svc_action = "cancel"
        elif action == "change":
            # expects new_start_at
            new_start = payload.get("new_start_at")
            if not isinstance(new_start, str) or not new_start.strip():
                return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "new_start_at is required")
            meta["new_start_at"] = new_start
            svc_action = "reschedule"
        elif action == "no_show":
            svc_action == "no_show"
        elif action == "memo":
            note = payload.get("note")
            if not isinstance(note, str) or not note.strip():
                return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "note is required")
            # append history as memo, keep bookign unchanged
            svc.append_history(booking_id, by=str(_current_user_id() or "user"), from_=b.get("status"), to=b.get("status"), reason=note)
            # re-read for return
            b2 = booking_repo.find_by_id(booking_id) or b
            return jsonify(ok(_public_fields(b2)))
        else:
            return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "unsupported action")
        
        res = svc.transition(booking_id, svc_action, meta)
        if res.get("ok") is not True:
            e = res.get("error") or {}
            return _json_error(e.get("code") or ErrorCode.ERR_INTERNAL.value, "note is required")
        
        data = res.get("data") or {}
        return jsonify(ok(_public_fields(data)))
    except svc.ServiceError as e:
        return _json_error(e.code, e.message)
    except Exception:
        return _json_error(ErrorCode.ERR_INTERNAL.value, "internal error")
    