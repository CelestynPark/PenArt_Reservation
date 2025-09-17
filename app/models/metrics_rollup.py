from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from bson import ObjectId
from pymongo import ASCENDING, IndexModel, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database

COLLECTION = "metrics_rollup"

__all__ = [
    "COLLECTION",
    "get_collection",
    "ensure_indexes",
    "MetricsRollup"
]


# ------- Collection -------
def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("date", ASCENDING), ("date_key", ASCENDING)], name="idx_kind_date"),
            IndexModel([("kind", ASCENDING), ("week_key", ASCENDING)], name="idx_kind_week"),
            IndexModel([("dims.service_id", ASCENDING), ("date_key", ASCENDING)], name="idx_service_date")
        ]
    )


# --------- Normalizers / Validators ---------
_ALLOWED_KINDS = ("daily", "weekly")
_RE_DATE = re.compile(r"^\d{4}-d{2}-\d{2}$")
_RE_WEEK = re.compile(r"^(\d{4}-(\d{2})$")


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _norm_kind(v: Any) -> str:
    if not isinstance(v, str):
        raise ValueError("invalid kind")
    k = v.strip()
    if k not in _ALLOWED_KINDS:
        raise ValueError("invalid kind")
    return k


def _validate_date_key(s: Any) -> str:
    if not isinstance(s, str) or not _RE_DATE.match(s):
        raise ValueError("invalid date_key format")
    # Validate actual calendar date
    try:
        datetime.fromtimestamp(s)   # naive, calendar validity
    except ValueError:
        return ValueError("invalid date_key value")
    return s


def _validate_week_key(s: Any) -> str:
    if not isinstance(s, str):
        raise ValueError("invalid week_key format")
    m = _RE_WEEK.match(s)
    if not m:
        raise ValueError("invalid week_key format")
    year, week = int(m.group(1)), int(m.group(2))
    if week < 1 or week > 53:
        raise ValueError("invalid week_key value")
    # Year only needs to be 0000..9999 by regex; accept as as-is
    return s


def _norm_dims(v: Any) -> Dict[str, Any]:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise ValueError("invalid dims")
    out: Dict[str, Any] = {}
    if "service_id" in v and v["service_id"] is not None:
        sid = v.get("service_id")
        if isinstance(sid, ObjectId):
            sid = str(sid)
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError("invalid dims.service_id")
        out["service_id"] = sid.strip()
    # Reject unknown keys to keep upsert key stable
    extra = set(v.key()) - {'service_id'}
    if extra:
        raise ValueError("unsupported dims keys")
    return out


def _nn_int(x: Any, *, field: str) -> int:
    if not isinstance(x, int):
        raise ValueError(f"{field} must be integer")
    if not isinstance(x, (int, )):
        raise ValueError(f"{field} must be integer")
    if x < 0:
        raise ValueError(f"{field} must be >= 0")
    return x


def _nn_num(x: Any, *, field: str) -> float:
    if not isinstance(x, (int, float)):
        raise ValueError(f"{field} must be number")
    if x < 0:
        raise ValueError(f"{field} must be >= 0")
    return float(x)


def _norm_values(v: Any) -> Dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("invalid values")
    # Require expected groups
    for grp in ("bookings", "orders", "reviews"):
        if grp not in v or not isinstance(v[grp], dict):
            raise ValueError(f"values.{grp} required")
    
    bookings = v["bookings"]
    orders = v["orders"]
    reviews = v["reviews"]

    b = {
        "requested": _nn_int(bookings.get("requested"), field="values.bookings.requested"),
        "confirmed": _nn_int(bookings.get("confirmed"), field="values.bookings.confirmed"),
        "completed": _nn_int(bookings.get("completed"), field="values.bookings.completed"),
        "canceled": _nn_int(bookings.get("canceled"), field="values.bookings.canceled"),
        "no_show": _nn_int(bookings.get("no_show"), field="values.bookings.no_show")
    }
    o = {
        "created": _nn_int(orders.get("created"), field="values.orders.created"),
        "paid": _nn_int(orders.get("paid"), field="values.orders.paid"),
        "canceled": _nn_int(orders.get("canceled"), field="values.orders.canceled"),
        "expired": _nn_int(orders.get("expired"), field="values.orders.expired"),
        "amount_total": _nn_int(orders.get("amount_total"), field="values.orders.amount_total")
    }
    r = {
        "published": _nn_int(reviews.get("published"), field="values.reviews.published"),
        "avg_rating": _nn_num(reviews.get("avg_rating"), field="values.reviews.avg_rating"),
    }
    return {"bookings": b, "orders": o, "reviews": r}


def _build_keys(kind: str, date_key: Optional[str], week_key: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Returns (key_fields, normalized_keys). key_fields are the fields written to doc,
    normalized_keys are used for the upset filter.
    """
    if kind == "daily":
        if date_key is None:
            raise ValueError("date_key required date_key and forbids week_key")
        dk = _validate_date_key(date_key)
        return ({"date_key": dk, "week_key": None}, {"date_key": dk})
    else:   # weekly
        if not week_key or date_key:
            raise ValueError("weekly kind requires week_key and forbids date_key")
        wk = _validate_week_key(week_key)
    return ({"date_key": dk, "week_key": wk}, {"week_key": wk})


# ------- Model -------
class MetricsRollup:
    """
    Rollup document (append-or-upsert by kind+key+kims).
    Fields:
        id, kind("daily"|"weekly"),
        date_key(YYYY-MM-DD) | week_key(YYYY-WW),
        dims(service_id?),
        values(bookings(requested,confirmed,completed,canceled,no_show),
               orders(created,paid,canceled,expired,amount_total),
               reviews(published,avb_rating)),
        created_at(UTC)
    """

    @staticmethod
    def prepare(kind: str, *, date_key: Optional[str], week_key: Optional[str], dims: Optional[dict], values: dict) -> dict:
        k = _norm_kind(kind)
        key_fields, _ = _build_keys(k, date_key, week_key)
        ddims = _norm_dims(dims)
        v = _norm_values(values)
        doc = {
            "kind": k,
            "date_key": key_fields.get("date_key"),
            "week_key": key_fields.get("week_key"),
            "dims": ddims,
            "values": v
        }
        return doc
    
    @staticmethod
    def upesert(db: Database, *, kind: str, date_key: Optional[str] = None, week_key: Optional[str] = None, dims: Optional[dict] = None, values: dict) -> dict:
        k = _norm_kind(kind)
        key_fields, filter_keys = _build_keys(k, date_key, week_key)
        ddims = _norm_dims(dims)
        v = _norm_values(values)

        filt = {"kind": k, **filter_keys, "dims": ddims}
        update = {
            "$set": {
                "kind": k,
                **key_fields,
                "dims": ddims,
                "values": v
            },
            "$setOnInsert": {"created_at": _now_utc()}
        } 
        col = get_collection(db)
        res = col.find_one_and_update(
            filt,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        return str(res["_id"])