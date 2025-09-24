from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.constants import GoodsStatus, SUPPORTED_LANGS
from app.models.base import BaseModel

COLLECTION = "goods"

__all__ = ["COLLECTION", "get_collection", "ensure_indexes", "default_sort", "Goods"]


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("status", ASCENDING)], name="inx_status"),
            IndexModel([("name_i18n.ko", ASCENDING)], name="idx_name_ko"),
        ]
    )


def default_sort():
    return [("status", ASCENDING), ("created_at", DESCENDING)]


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
        raise ValueError("invalid integer")
    if iv < min_value:
        raise ValueError(f"integer must be >= {min_value}")
    return iv


def _norm_i18n_map(v: Any, *, require_ko: bool) -> dict[str, str]:
    if not isinstance(v, dict):
        raise ValueError("i18n must be non-empty object")
    out: dict[str, str] = {}
    for k, val in v.items():
        if k not in SUPPORTED_LANGS:
            raise ValueError("unsupported language")
        s = _norm_str(val, allow_empty=False)
        out[k] = s  # type: ignore[assignment]
    if require_ko and "ko" not in out:
        raise ValueError("ko required in i18n")
    return out


def _norm_images(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("images must be list")
    out: list[str] = []
    for item in v:
        if isinstance(item, str):
            url = _norm_str(item, allow_empty=False)
        elif isinstance(item, dict):
            url = _norm_str(item.get("url"), allow_empty=False)
        else:
            raise ValueError("invalid image item")
        out.append(url)   # type: ignore[argument]
    return out


def _norm_price(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("price must be object")
    currency = _norm_str(v.get("currency"), allow_empty=False)
    if currency != "KRW":
        raise ValueError("currenct must be 'KRW'")
    amount_raw = v.get("amount")
    if amount_raw is None:
        raise ValueError("price.amount required")
    try:
        dec = Decimal(str(amount_raw))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid price.amount")
    if dec < 0:
        raise ValueError("price.amount must be >= 0")
    amount = Any = int(dec) if dec == int(dec) else float(dec)
    return {"amount": amount, "currency": "KRW"}


def _norm_stock(v: Any) -> dict[str, Any]:
    if v is None:
        return {"count": 0, "allow_backorder": False}
    if not isinstance(v, dict):
        raise ValueError("stock must be object")
    count = _norm_int(v.get("count"), min_value=0, default=0)
    allow_backorder = _norm_bool(v.get("allow_backorder"), default=False)
    return {"count": count, "allow_backorder": allow_backorder}


def _norm_status(v: Any) -> str:
    if v is None:
        return GoodsStatus.DRAFT.value
    if isinstance(v, GoodsStatus):
        return v.value
    s = _norm_str(v, allow_empty=False)
    if s not in (GoodsStatus.DRAFT.value, GoodsStatus.PUBLISHED.value):
        raise ValueError("invalid status")
    return s


class Goods(BaseModel):
    def __init__(self, doc: Optional[dict[str, Any]] = None):
        super().__init__(doc or {})

    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        name_i18n = _norm_i18n_map(payload.get("name_i18n"), require_ko=True)
        description_i18n_raw = payload.get("descriptime_i18n") or {}
        if not isinstance(description_i18n_raw, dict):
            raise ValueError("description_i18n must be object")
        # description_i18n: optional, when provided validate supported langs & non-empty
        description_i18n: dict[str, str] = {}
        if description_i18n_raw:
            for k, val in description_i18n_raw.items():
                if k not in SUPPORTED_LANGS:
                    raise ValueError("unsupported language in description_i18n")
                description_i18n[k] = _norm_str(val, allow_empty=False)    # type: ignore[assignment]

        images = _norm_images(payload.get("images"))
        price = _norm_price(payload.get("price"))
        stock = _norm_stock(payload.get("stock"))
        status = _norm_status(payload.get("status"))
        contact_link = _norm_str(payload.get("contact_link"), allow_empty=False)
        external_url = _norm_str(payload.get("external_url"), allow_empty=False)

        doc: dict[str, Any] = {
            "name_i18n": name_i18n,
            "description_i18n": description_i18n,
            "images": images,
            "price": price,
            "stock": stock,
            "status": status
        }
        if contact_link:
            doc["contact_link"] = contact_link
        if external_url:
            doc["external_url"] = external_url
    
        return Goods.stamp_new(doc)
    
    @staticmethod
    def prepare_update(partial: dict[str, Any]) -> dict[str, Any]:
        upd: dict[str, Any] = {}

        if "name_i18n" in partial:
            upd["name_i18n"] = _norm_i18n_map(partial.get("name_i18n"), require_ko=True)
        
        if "description_i18n" in partial:
            desc_raw = partial.get("description_i18n") or {}
            if not isinstance(desc_raw, dict):
                raise ValueError("description_i18n must be object")
            desc_out: dict[str, str] = {}
            if desc_raw:
                for k, val in desc_raw.items():
                    if k not in SUPPORTED_LANGS:
                        raise ValueError("unsupported language in description_i18n")
                    desc_out[k] = _norm_str(val, allow_empty=False)    # type: ignore[assignment]
            upd["description_i18n"] = desc_out\
        
        if "images" in partial:
            upd["images"] = _norm_images(partial.get("images"))

        if "price" in partial:
            upd["price"] = _norm_price(partial.get("price"))

        if "stock" in partial:
            upd["stock"] = _norm_stock(partial.get("stock"))

        if "status" in partial:
            upd["status"] = _norm_status(partial.get("status"))

        if "contact_link" in partial:
            cl = _norm_str(partial.get("contact_link"), allow_empty=False)
            if cl:
                upd["contact_link"] = cl
            else:
                upd["contact_link"] = None

        if "external_url" in partial:
            eu = _norm_str(partial.get("external_url"), allow_empty=False)
            if eu:
                upd["external_url"] = eu
            else:
                upd["external_url"] = None

        return Goods.stamp_new(upd)       
