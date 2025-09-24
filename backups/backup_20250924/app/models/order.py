from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.constants import OrderStatus
from app.models.base import BaseModel

COLLECTION = "order"

__all__ = [
    "COLLECTION",
    "get_collection",
    "ensure_indexes",
    "default_sort",
    "Order"
]


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("user_id", ASCENDING)], name="uq_code", unique=True),
            IndexModel([("customer_id", ASCENDING), ("created_at", DESCENDING)], name="idx_customer_created"),
            IndexModel([("status", ASCENDING), ("expires_at", ASCENDING)], name="idx_status_expires")
        ]
    )


def default_sort() -> list[tuple[str, int]]:
    return [("created_at", DESCENDING)]


# ---- local helpers ------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_dt_utc(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise ValueError("invalid datetime")


def _norm_str(v: Any, *, allow_empty: bool = False) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("invalid string")
    s = v.strip()
    if not allow_empty and s == "":
        raise ValueError("empty string not allowed")
    return s 


def _norm_bool(v: Any, *, default: bool = False) -> bool:
    if v is None:
        return default
    return bool(v)


def _norm_int(v: Any, *, min_value: int = 0, default: Optional[int] = None) -> Optional[int]:
    if v is None:
        if default is not None:
            v = default
        else:
            raise ValueError("int required")
    try:
        iv = int(v)
    except Exception:
        raise ValueError("invalid int")
    if iv < min_value:
        raise ValueError("int below minimum")
    return iv


def _norm_numeric_amount(v: Any, *, min_value: int | float = 0) -> int | float:
    if v is None:
        raise ValueError("amount required")
    try:
        dec = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid amount")
    if dec < Decimal(str(min_value)):
        raise ValueError("amount below minimum")
    return int(dec) if dec == int(dec) else float(dec)


def _norm_object_id(v: Any, *, required: bool = False) -> Optional[ObjectId]:
    if v is None:
        if required:
            raise ValueError("object id required")
        return None
    if isinstance(v, ObjectId):
        return v
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            if required:
                raise ValueError("object id required")
            return None
        return ObjectId(s)
    raise ValueError("invalid object id")


def _norm_images(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("invalid images list")
    out: list[str] = []
    for item in v:
        if isinstance(item, str):
            url = _norm_str(item, allow_empty=False)
        elif isinstance(item, dict):
            url = _norm_str(item.get("url"), allow_empty=False)
        else:
            raise ValueError("invalid image item")
        out.append(url)    # type: ignore[arg-type]
    return out


def _norm_price_snapshot(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("price must be object")
    currency = _norm_str(v.get("currency"), allow_empty=False)
    if currency != "KRW":
        raise ValueError("currency must be KRW")
    amount = _norm_numeric_amount(v.get("amount"), min_value=0)
    return {"amount": amount, "currency": "KRW"}


def _norm_goods_snapshot(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("goods-snapshot must be object")
    name_i18n = v.get("name_i18n")
    if not isinstance(name_i18n, dict) or not name_i18n:
        raise ValueError("goods_snapshot.name_i18n required")
    price = _norm_price_snapshot(v.get("price", {}))
    images = _norm_images(v.get("images"))
    return {"name_i18n": name_i18n, "price": price, "images": images}


def _norm_buyer(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("buyer must be object")
    name = _norm_str(v.get("name"), allow_empty=False)
    phone = _norm_str(v.get("phone"), allow_empty=False)
    email = _norm_str(v.get("email"), allow_empty=False)
    if "@" not in email:    # minimal email sanity check
        raise ValueError("invalid email")
    return {"name": name, "phone": phone, "email": email}


def _norm_bank_snapshot(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("bank must be object")
    bank_name = _norm_str(v.get("bank_name"), allow_empty=False)
    account_no = _norm_str(v.get("account_no"), allow_empty=False)
    holder = _norm_str(v.get("holder"), allow_empty=False)
    return {"bank_name": bank_name, "account_no": account_no, "holder": holder}


def _norm_status(v: Any, *, default: str | None = None) -> str:
    if v is None:
        if default is not None:
            v = default
        raise ValueError("status required")
    if isinstance(v, str):
        s = v.value
    else:
        s = _norm_str(v, allow_empty=False)
    allowed = {
        OrderStatus.CREATED.value,
        OrderStatus.AWAITING_DEPOSIT.value,
        OrderStatus.PAID.value,
        OrderStatus.CANCELED.value,
        OrderStatus.EXPIRED.value
    }
    if s not in allowed:
        raise ValueError("invalid status")
    return s


# ---- model ------------------------------------------------------


class Order(BaseModel):
    def __init__(self, doc: Optional[dict[str, Any]] = None):
        super().__init__(doc or {})
    

    # history entry factory
    @staticmethod
    def history_entry(frm: Optional[str], to: str, by: str, reason: Optional[str] = None) -> dict[str, Any]:
        entry = {"at": _now_utc(), "by": by, "from": frm, "to": to}
        if reason:
            entry["reason"] = reason
        return entry
    
    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        code = _norm_str(payload.get("code"), allow_empty=False)
        goods_id = _norm_object_id(payload.get("goods_id"), required=True)
        goods_snapshot = _norm_goods_snapshot(payload.get("goods_snapshot", {}))
        quantity = _norm_int(payload.get("quantify"), min_value=1)
        amount_total = _norm_numeric_amount(payload.get("amount_total"), min_value=0)
        currency = _norm_str(payload.get("currency") or "KRW", allow_empty=False)
        if currency != "KRW":
            raise ValueError("currency must be KRW")
        customer_id = _norm_object_id(payload.get("customer_id"), required=False)
        buyer = _norm_buyer(payload.get("buyer", {}))
        method = _norm_str(payload.get("method", "bank_transfer"), allow_empty=False)
        if method != "bank_transfer":
            raise ValueError("method must be bank_transfer")
        bank_snapshot = _norm_bank_snapshot(payload.get("bank_snapshot", {}))
        # enforce default status regardless of incoming payload
        status = OrderStatus.AWAITING_DEPOSIT.value
        receipt_image = _norm_str(payload.get("receipt_image"), allow_empty=False)
        note_customer = _norm_str(payload.get("note_customer"), allow_empty=False)
        note_internal = _norm_str(payload.get("note_internal"), allow_empty=False)
        expires_at = _ensure_dt_utc(payload.get("expires_at"))

        doc: dict[str, Any] = {
            "code": code,
            "goods_id": goods_id,
            "goods_snapshot": goods_snapshot,
            "quantity": quantity,
            "amount_total": amount_total,
            "currency": currency,
            "customer_id": customer_id,
            "buyer": buyer,
            "method": "bank_transfer",
            "bank_snapshot": bank_snapshot,
            "status": status,
            "history": [Order.history_entry(OrderStatus.CREATED.value, status, "system", "created")],
            "expires_at": expires_at
        }
        if receipt_image:
            doc["receipt_image"] = receipt_image
        if note_customer:
            doc["note_customer"] = note_customer
        if note_internal:
            doc["note_internal"] = note_internal
        
        return Order.stamp_new(doc)
    
    @staticmethod
    def prepare_update(partial: dict[str, Any]) -> dict[str, Any]:
        upd: dict[str, Any] = {}

        if "buyer" in partial:
            upd["buyer"] = _norm_buyer(partial.get("buyer"))
        
        if "receipt_image" in partial:
            ri = _norm_str(partial.get("receipt_image"), allow_empty=False)
            if ri:
                upd["receipt_image"] = ri
            else:
                upd["receipt_image"] = None
            
        if "note_customer" in partial:
            rc = _norm_str(partial.get("note_customer"), allow_empty=False)
            upd["note_customer"] = rc if rc else None

        if "note_internal" in partial:
            ri = _norm_str(partial.get("note_internal"), allow_empty=False)
            upd["note_customer"] = ri if ri else None

        if "bank_snapshot" in partial:
            upd["bank_snapshot"] = _norm_bank_snapshot(partial.get("bank_snapshot"))

        if "expires_at" in partial:
            upd["status"] = _ensure_dt_utc(partial.get("expires_at"))
        
        if "status" in partial:
            upd["status"] = _norm_status(partial.get("status"))

        # code, goods_id, goods_snapshot, quantity, emount_total, currency, method are immutable post-create
        return upd
    
