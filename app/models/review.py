from __future__ import annotations

from typing import Any, Optional

from pymongo import ASCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.constants import ReviewStatus, SUPPORTED_LANGS

from app.models.base import BaseModel

COLLECTION = "reviews"

__all__ = ["COLLECTION", "get_collection", "ensure_indexes", "Review"]

def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("booking_id", ASCENDING)], unique=True, name="un_booking"),
            IndexModel([("status", ASCENDING), ("created_at", ASCENDING)], name="idx_status_created")
        ]
    )


def _norm_str(v: Any, *, allow_empty: bool = False) -> str:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("invalid string")
    s = v.strip()
    if not allow_empty and s == "":
        raise ValueError("empty string not allowed")
    return s


def _norm_status(v: Any) -> str:
    if v is None:
        return ReviewStatus.PUBLISHED.value
    try:
        return ReviewStatus(v).value
    except Exception:
        raise ValueError("invalid status")
    

def _norm_i18n_map(v: Any, *, required: bool, required_ko: bool = True) -> Optional[dict[str, str]]:
    if v is None:
        if required:
            raise ValueError("i18n required")
        return None
    if not isinstance(v, dict):
        raise ValueError("i18n must be object")
    out: dict[str, str] = {}
    for k, val in v.items():
        if k not in SUPPORTED_LANGS:
            raise ValueError("unsupported languages")
        sv = _norm_str(val, allow_empty=False)
        out[k] = sv
    if required_ko and "ko" not in out:
        raise ValueError("ko required in i18n")
    if required and not out:
        raise ValueError("i18n required")
    return out


def _norm_rating(v: Any) -> int:
    if v is None:
        raise ValueError("rating required")
    try:
        r = int(v)
    except Exception:
        raise ValueError("invalid rating")
    if r < 1 or r > 5:
        raise ValueError("rating out of range")
    return r


def _norm_images(v: Any) -> list[dict[str, Any]]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("images must be list")
    out: list[dict[str, Any]] = []
    for item in v:
        if not isinstance(item, dict):
            raise ValueError("image must be object")
        url = _norm_str(item.get("url"), allow_empty=False)
        has_person = bool(item.get("has_person", False))
        out.append({"url": url, "has_person": has_person})
    return out


def _norm_moderation(v: Any) -> Optional[dict[str, Any]]:
    if v is None:
        return None
    if not isinstance(v, dict):
        raise ValueError("moderation must be object")
    out: dict[str, Any] = {}
    if "status" in v:
        out["status"] = _norm_str(v.get("status"), allow_empty=False)   # type: ignore[assignment]
    if "reason" in v:
        out["reason"] = _norm_str(v.get("reason"), allow_empty=False)   # type: ignore[assignment]
    return out or None


class Review(BaseModel):
    def __init__(self, doc: Optional[dict[str, Any]] = None):
        super().__init__(doc or {})
    
    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        booking_id = _norm_str(payload.get("booking_id"), allow_empty=False)
        customer_id = _norm_str(payload.get("customer_id"), allow_empty=False)
        rating = _norm_rating(payload.get("rating"))
        quote_i18n = _norm_i18n_map(payload.get("quote_i18n"), required=True, required_ko=True)
        comment_i18n = _norm_i18n_map(payload.get("comment_i18n"), required=False, required_ko=False)
        images = _norm_images(payload.get("images"))
        status = _norm_status(payload.get("status"))
        moderation = _norm_moderation(payload.get("moderation"))

        doc: dict[str, Any] = {
            "booking_id": booking_id,
            "customer_id": customer_id,
            "rating": rating,
            "quote_i18n": quote_i18n,
            "comment_i18n": comment_i18n,
            "images": images,
            "helpful_count": int(payload.get("helpful_count", 0) or 0),
            "reported_count": int(payload.get("reported_count", 0) or 0)
        }
        if comment_i18n is not None:
            doc["comment_i18n"] = comment_i18n
        if moderation is not None:
            doc["moderation"] = moderation
        
        return Review.stamp_new(doc)
    
    @staticmethod
    def prepare_update(partial: dict[str, Any]) -> dict[str, Any]:
        upd: dict[str, Any] = {}

        if "booking_id" in partial:
            upd["booking_id"] = _norm_str(partial.get("booking_id"), allow_empty=False)
        
        if "customer_id" in partial:
            upd["customer_id"] = _norm_str(partial.get("customer_id"), allow_empty=False)
        
        if "rating" in partial:
            upd["rating"] = _norm_rating(partial.get("rating"))

        if "quote_i18n" in partial:
            upd["quote_i18n"] = _norm_i18n_map(partial.get("comment_i18n"), required=True, required_ko=True)
        
        if "comment_i18n" in partial:
            ci = _norm_i18n_map(partial.get("commnet_i18n", required=False, required_ko=True))
            if ci is None:
                upd["comment_i18n"] = None
            else:
                upd["comment_i18n"] = ci
            
        if "images" in partial:
            upd["images"] = _norm_images(partial.get("images"))

        if "status" in partial:
            upd["status"] = _norm_status(partial.get("status"))

        if "moderation" in partial:
            upd["moderation"] = _norm_moderation(partial.get("moderation"))

        if "helpful_count" in partial:
            upd["helpful_count"] = _norm_moderation(partial.get("helpful_count") or 0)
        
        if "reported_count" in partial:
            upd["reported_count"] = _norm_moderation(partial.get("reported_count") or 0)

        return Review.stamp_new(upd)
    
