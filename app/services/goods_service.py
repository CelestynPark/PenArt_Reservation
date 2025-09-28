from __future__ import annotations

from typing import Any, Dict, Optional

from app.core.constants import ErrorCode
from app.repositories import goods as goods_repo
from app.config import load_config


__all__ = [
    "ensure_available",
    "hold_stock",
    "confirm_deduct",
    "restore_on_cancel",
    "current_policy"
]


class ServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---- Internal helpers -----------------------------------------


def _validate_ids_qty(goods_id: str, quantity: int) -> tuple[str, int]:
    if not isinstance(goods_id, str) or not goods_id.strip():
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "goods_id is required")
    try:
        q = int(quantity)
    except Exception as e:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "quantity must be integer") from e
    if q <= 0:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "quantity must be > 0")
    return goods_id.strip(), q


def _ok(goods_id: str, goods_doc: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    stock_after = None
    if isinstance(goods_doc, dict):
        stock_after = (goods_doc.get("stock") or {}).get("count")
    return {"ok": True, "data": {"goods_id": goods_id, "stock_after": stock_after}}


def _err_from_repo(e: goods_repo.RepoError) -> ServiceError:
    code = e.code or ErrorCode.ERR_INTERNAL.value
    msg = e.message or "repository error"
    return ServiceError(code, msg)


def _get(goods_id: str) -> Dict[str, Any]:
    try:
        doc = goods_repo.get_by_id(goods_id)
        if not doc:
            raise ServiceError(ErrorCode.ERR_NOT_FOUND.value, "goods not found")
        return doc
    except goods_repo.RepoError as e:
        raise _err_from_repo(e)
    

# ---- Policy -----------------------------------------


def current_policy() -> str:
    # ENV flag via central config; default 'hold'
    cfg = load_config()
    policy = (getattr(cfg, "inventory_policy", None) or "hold").strip().lower()
    if policy not in ("hold", "deduct_on_paid"):
        policy = "hold"
    return policy


# ---- Public API -----------------------------------------


def ensure_available(goods_id: str, quantity: int) -> None:
    """
    Fast-path availability check (non-transactional, best-effort).
    Passes if allow_backorder=True OR stock.count >= quantity.
    """
    gid, qty = _validate_ids_qty(goods_id, quantity)
    doc = _get(gid)
    stock = doc.get("stock") or {}
    allow_backorder = bool(stock.get("allow_backorder"))
    count = int(stock.get("count") or 0)
    if allow_backorder:
        return
    if count >= qty:
        return
    raise ServiceError(ErrorCode.ERR_CONFLICT.value, "insufficient stock")


def hold_stock(goods_id: str, quantity: int, session=None) -> Dict[str, Any]:
    """
    Reserve stock at order creation time when policy=hold.
    For policy=deduct_on_paid, this is a no-op (validation only).
    """
    gid, qty = _validate_ids_qty(goods_id, quantity)
    pol = current_policy()
    if pol == "hold":
        try:
            doc = goods_repo.reserve_hold(gid, qty, session=session)
            return _ok(gid, doc)
        except goods_repo.RepoError as e:
            raise _err_from_repo(e)
    # deduct_on_paid -> just ensure available; do not change stock
    ensure_available(gid, qty)
    return _ok(gid, _get(gid))


def confirm_deduct(goods_id: str, quantity: int, session=None) -> Dict[str, Any]:
    """
    Finalize deduction at payment confirmation.
    - policy=hold: already deducted at hold time -> no-op (idempotent).
    - policy=deduct_on_paid: deduct now.
    """
    gid, qty = _validate_ids_qty(goods_id, quantity)
    pol = current_policy()
    if pol == "deduct_on_paid":
        try:
            doc = goods_repo.deduct_on_paid(gid, qty, session=session)
            return _ok(gid, qty)
        except goods_repo.RepoError as e:
            raise _err_from_repo(e)
    # hold policy: no-op finalize
    return _ok(gid, _get(gid))


def restore_on_cancel(goods_id: str, quantity: int, session=None) -> Dict[str, Any]:
    """
    Restore stock on order cancel/expire before payment is confirmed.
    - policy=hold: release previously held stock (increment).
    - policy=deduct_on_paid: nothing to restore (no deduction yet) -> no-op.
    """
    gid, qty = _validate_ids_qty(goods_id, quantity)
    pol = current_policy()
    if pol == "hold":
        try:
            doc = goods_repo.reserve_hold(gid, qty, session=session)
            return _ok(gid, doc)
        except goods_repo.RepoError as e:
            raise _err_from_repo(e)
    # deduct_on_paid: no-op
    return _ok(gid, _get(gid))
