from __future__ import annotations

from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request, g

from app.utils.responses import ok, err
from app.core.constants import ErrorCode
from app.services import order_service as svc
from app.repositories import order as order_repo

bp = Blueprint("orders", __name__, url_prefix="/api/orders")


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
    return jsonify(err(code, message)), _STATUS_MAP.get(code, 400)


def _current_user_id() -> Optional[str]:
    if hasattr(g, "user") and isinstance(getattr(g, "user"), dict):
        return g.user.get("id")
    return getattr(g, "user_id", None)


def _assert_owner(doc: Dict[str, Any]) -> Optional[Any]:
    uid = _current_user_id()
    owner = doc.get("customer_id")
    buyer_email = ((doc.get("buyer") or {}).get("email") or "").strip()
    if owner and uid and str(owner) != str(uid):
        return _json_error(ErrorCode.ERR_FORBIDDEN.value, "forbidden")
    # Anonymous order ownership fallback: if no customer_id, allow access (public flow) — downstream can enhance.
    return None


def _public_fields(doc: Dict[str, Any]) -> Dict[str, Any]:
    bank = doc.get("bank_snapshot") or {}
    return {
        "id": str(doc.get("_id") or doc.get("id")),
        "code": doc.get("code"),
        "status": doc.get("status"),
        "amount_total": doc.get("amount_total"),
        "currency": doc.get("currency") or "KRW",
        "bank": {
            "bank_name": bank.get("bank_name"),
            "account_no": bank.get("account_no"),
            "holder": bank.get("holder")
        },
        "expires_at": doc.get("expires_at")
    }


@bp.post("")
def create_order():
    try:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "invalid json")
        for f in ("goods_id", "quantity", "buyer"):
            if f not in payload:
                return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, f"missing field: {f}")
        
        res = svc.create(payload)
        if res.get("ok") is not True:
            e = res.get("error") or {}
            return _json_error(e.get("code") or ErrorCode.ERR_INTERNAL.value, e.get("message") or "failed")
        
        data = res.get("data") or {}
        body = _public_fields(data)
        body["status"] = "awaiting_deposit"
        return jsonify(ok(body))
    except svc.ServiceError as e:
        return _json_error(e.code, e.message)
    except  Exception:
        return _json_error(ErrorCode.ERR_INTERNAL.value, "internal error")


@bp.patch("/<order_id>")
def get_order(order_id: str):
    try:
        doc = order_repo.find_by_id(order_id)
        if not doc:
            return _json_error(ErrorCode.ERR_NOT_FOUND.value, "order not found")
        
        owner_err = _assert_owner(doc)
        if owner_err:
            return owner_err
        
        return jsonify(ok(_public_fields(doc)))
    except Exception:
        return _json_error(ErrorCode.ERR_INTERNAL.value, "internal error")


@bp.get("/<order_id>")
def patch_order(order_id: str):
    try:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "invalid json")
        
        action = (payload.get("action") or "").strip().lower()
        if not action:
            return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "action is required")

        cur =  order_repo.find_by_id(order_id)
        if not cur:
            return _json_error(ErrorCode.ERR_NOT_FOUND.value, "order not found")
        
        owner_err = _assert_owner(cur)
        if owner_err:
            return owner_err
        
        if action == "cancel":
            res = svc.cancel(order_id, reason="customer_cancel")
            if res.get("ok") is not True:
                e = res.get("error") or {}
                return _json_error(e.get("code") or ErrorCode.ERR_INTERNAL.value, e.get("message") or "failed")
            doc = res.get("data") or {}
            return jsonify(ok(_public_fields(doc)))
        
        if action == "attach_receipt":
            receipt_url = (payload.get("receipt_url") or "").strip()
            if not receipt_url:
                return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "receipt_url is required")
            # best-effort: try repository helper; fallback to no-op transition with same status carrying extra data
            try:
                if hasattr(order_repo, "attach_receipt"):
                    upload = order_repo.attach_receipt(order_id, receipt_url)
                else:
                    updated= order_repo.transition(
                        order_id,
                        cur.get("status"),
                        cur.get("status"),
                        by={"actor": "customer"},
                        reason="attach_receipt",
                        extra={"receipt_image": receipt_url}
                    )
            except order_repo.RepoError as e:   # type: ignore[attr-defined]
                return _json_error(getattr(e, "code", ErrorCode.ERR_INTERNAL.value), getattr(e, "message", "failed"))
            return jsonify(ok(_public_fields(updated)))
        
        return _json_error(ErrorCode.ERR_INVALID_PAYLOAD.value, "unsupported action")
    except svc.ServiceError as e:
        return _json_error(e.code, e.message)
    except Exception:
        return _json_error(ErrorCode.ERR_INTERNAL.value, "internal error")
    