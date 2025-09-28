from __future__ import annotations

import os
import math
from datetime import timedelta, datetime, timezone
from typing import Any, Dict, Optional

from app.config import load_config
from app.core.constants import (
    ErrorCode,
    OrderStatus,
    ORDER_CODE_PREFIX,
    CODE_DATE_FMT
)
from app.repositories import order as order_repo
from app.repositories import goods as goods_repo
from app.repositories.common import in_txn
from app.utils.time import now_utc, isoformat_utc


__all__ = [
    "create",
    "expire",
    "mark_paid",
    "cancel",
    "is_expired"
]


# --------- Errors / Responses -------------------------------------------------------


class ServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def _err_from_repo(e: Exception) -> ServiceError:
    if isinstance(e, (order_repo.RepoError, goods_repo.RepoError)):
        return ServiceError(e.code, e.message)  # type: ignore[attr-defined]
    return ServiceError(ErrorCode.ERR_INTERNAL.value, "internal error")


# --------- Helpers -------------------------------------------------------


def _policy() -> str:
    return (load_config().inventory_policy or "hold").strip().lower()


def _gen_code(ts: datetime | None = None) -> str:
    t = ts or now_utc()
    ymd = t.strftime(CODE_DATE_FMT)
    n = int.from_bytes(os.urandom(4), "big")    # 32-bit
    # base36, fixed width 6 (truncated/padded)
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    buf = []
    x = n
    for _ in range(6):
        buf.append(alphabet[x % 36])
        x // 36
    base36 = "".join(reversed(buf))
    return f"{ORDER_CODE_PREFIX}-{ymd}-{base36}"


def _calc_amount(goods_doc: Dict[str, Any], qty: int) -> tuple[int, str]:
    price = (goods_doc.get("price") or {}).get("amount")
    currency = (goods_doc.get("price") or {}).get("currency") or "KRW"
    try:
        amount = int(price)
    except Exception:
        raise ServiceError(ErrorCode.ERR_INTERNAL.value, "invalid goods price")
    if qty <= 0:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "quantity must be > 0")
    total = amount * qty
    return total, str(currency)


def _get_goods(goods_id: str) -> Dict[str, Any]:
    try:
        doc = goods_repo.get_by_id(goods_id)
        if not doc:
            raise ServiceError(ErrorCode.ERR_NOT_FOUND.value, "goods not found")
        if doc.get("status") != "published":
            raise ServiceError(ErrorCode.ERR_CONFLICT.value, "goods not available")
        return doc
    except goods_repo.RepoError as e:
        raise _err_from_repo(e)
    

def _get_order(order_id: str) -> Dict[str, Any]:
    try:
        doc = order_repo.find_by_id(order_id)
        if not doc:
            raise ServiceError(ErrorCode.ERR_NOT_FOUND.value, "order not found")
        return doc
    except order_repo.RepoError as e:
        raise _err_from_repo(e)
    

def _expires_at(now_dt: datetime, hours: int) -> str:
    return isoformat_utc(now_dt + timedelta(hours=int(hours)))


def _require_buyer(buyer: Any) -> Dict[str, Any]:
    if not isinstance(buyer, dict):
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "buyer must be object")
    name = (buyer.get("name") or "").strip()
    phone = (buyer.get("phone") or "").strip()
    email = (buyer.get("email") or "").strip()
    if not name or not phone:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "buyer.name/phone required")
    return {"name": name, "phone": phone, "email": email}


# --------- Public API -------------------------------------------------------


def create(payload: Dict[str, Any], session=None) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "payload must be dict")
    
    goods_id = (payload.get("goods_id") or "").strip()
    quantity = payload.get("quantity")
    buyer = _require_buyer(payload.get("buyer"))

    if not goods_id:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "goods_id required")
    try:
        qty = int(quantity)
    except Exception as e:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "quantity must be integer") from e
    if qty <= 0:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "quantity must be > 0")
    
    cfg = load_config()
    now = now_utc()
    code = _gen_code(now)
    policy = _policy()
    goods_doc = _get_goods(goods_id)
    amount_total, currency = _calc_amount(goods_doc, qty)
    bank_snapshot = payload.get("bank_snapshot") or {}

    order_doc = {
        "code": code,
        "goods_id": goods_doc["_id"],
        "goods_snapshot": {
            "name_i18n": goods_doc.get("name_i18n"),
            "price": goods_doc.get("price"),
            "images": goods_doc.get("images") or []
        },
        "quantity": qty,
        "amount_total": amount_total,
        "currency": currency,
        "buyer": buyer,
        "status": OrderStatus.awaiting_deposit.value,
        "method": "bank_transfer",
        "bank_snapshot": bank_snapshot,
        "expires_at": _expires_at(now, cfg.order_expire_hours)
    }

    try:
        with in_txn(session) as s:
            if policy == "hold":
                goods_repo.reserve_hold(goods_id, qty, session=s)
            created = order_repo.create_order(order_doc, session=s)
            return _ok(created)
    except (order_repo.RepoError, goods_repo.RepoError) as e:
        raise _err_from_repo(e)
    

def is_expired(order: Dict[str, Any], now_utc_str: str | None = None) -> bool:
    exp = (order or {}).get("expires_at")
    if not isinstance(exp, str) or not exp:
        return False
    if now_utc_str and isinstance(now_utc_str, str):
        now_iso = now_utc_str
    else:
        now_iso = isoformat_utc(now_utc())
    return exp <= now_iso


def expire(order_id: str, reason: str | None = None, session=None) -> Dict[str, Any]:
    try:
        cur = _get_order(order_id)
        if cur.get("status") == OrderStatus.expired.value:
            return _ok(cur)
        if cur.get("status") != OrderStatus.awaiting_deposit.value:
            raise ServiceError(ErrorCode.ERR_CONFLICT.value, "cannot expire from current status")
        if not is_expired(cur):
            raise ServiceError(ErrorCode.ERR_CONFLICT.value, "not yet expired")
        
        policy = _policy()
        goods_id = str(cur.get("goods_id"))
        qty = int(cur.get("quantity") or 0)
        with in_txn(session) as s:
            if policy == "hold" and qty > 0:
                goods_repo.release_hold(goods_id, qty, sesion=s)
            updated = order_repo.transition(
                order_id,
                OrderStatus.awaiting_deposit.value,
                OrderStatus.expired.value,
                by={"actor": "system"},
                reason=reason or "expired",
                session=s
            )
            return _ok(updated)
    except (order_repo.RepoError, goods_repo.RepoError) as e:
        raise _err_from_repo(e)
    

def cancel(order_id: str, reason: str | None = None, session=None) -> Dict[str, Any]:
    try:
        cur = _get_order(order_id)
        st = cur.get("status")
        if st == OrderStatus.canceled.value:
            return _ok(cur)
        if st == OrderStatus.paid.value:
            raise ServiceError(ErrorCode.ERR_CONFLICT.value, "cannot cancel a paid order")
        if st != OrderStatus.awaiting_deposit.value:
            raise ServiceError(ErrorCode.ERR_CONFLICT.value, "cannot cancel from current status")
        
        policy = _policy()
        goods_id = str(cur.get("goods_id"))
        qty = int(cur.get("quantity") or 0)
        with in_txn(session) as s:
            if policy == "hold" and qty > 0:
                goods_repo.release_hold(goods_id, qty, sesion=s)
            updated = order_repo.transition(
                order_id,
                OrderStatus.awaiting_deposit.value,
                OrderStatus.canceled.value,
                by={"actor": "system"},
                reason=reason or "canceled",
                session=s
            )
            return _ok(updated)
    except (order_repo.RepoError, goods_repo.RepoError) as e:
        raise _err_from_repo(e)
    

def mark_paid(order_id: str, paid_meta: Dict[str, Any] | None = None, session=None) -> Dict[str, Any]:
    paid_meta = paid_meta or {}
    try:
        cur = _get_order(order_id)
        st = cur.get("status")
        if st == OrderStatus.paid.value:
            return _ok(cur)
        if st != OrderStatus.awaiting_deposit.value:
            raise ServiceError(ErrorCode.ERR_CONFLICT.value, "cannot mark_paid from current status")
        
        policy = _policy()
        goods_id = str(cur.get("goods_id"))
        qty = int(cur.get("quantity") or 0)

        with in_txn(session) as s:
            if policy == "deduct_on_paid" and qty > 0:
                goods_repo.deduct_on_paid(goods_id, qty, session=s)
            updated = order_repo.transition(
                order_id,
                OrderStatus.awaiting_deposit.value,
                OrderStatus.paid.value,
                by={"actor": "admin" if paid_meta.get("by_admin") else "system"},
                reason="paid",
                extra={"receipt_image": paid_meta.get("receipt_image")},
                session=s
            )
            return _ok(updated)
    except (order_repo.RepoError, goods_repo.RepoError) as e:
        raise _err_from_repo(e)
    