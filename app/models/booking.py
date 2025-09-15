from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import ASCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.constants import BookingStatus, Source
from app.models.base import BaseModel
from app.utils.time import iso

COLLECTION = "bookings"

__all__ = ["COLLECTION", "get_collection", "ensure_indexes", "Booking"]


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("service_id", ASCENDING), ("start_at", ASCENDING)], unique=True, name="uq_service_start"),
            IndexModel([("code", ASCENDING)], name="idx_code"),
            IndexModel([("customer_id", ASCENDING), ("start_at", ASCENDING)], name="idx_customer_start"),
        ]
    )


UTC = timezone.utc


def _parse_utc(v: Any) -> datetime:
    if isinstance(v, datetime):
        return (v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC))
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            raise ValueError("invalid datetime")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    raise ValueError("invalid datetime")


def _norm_status(v: Any) -> str:
    if v is None:
        return BookingStatus.REQUESTED.value
    try:
        return BookingStatus(v).value
    except Exception:
        raise ValueError("invalid status")


def _norm_source(v: Any) -> str:
    if v is None:
        return Source.WEB.value
    try:
        return Source(v).value
    except Exception:
        raise ValueError("invalid source")


def _norm_str(v: Any, *, allow_empty: bool = True) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("invalid string")
    s = v.strip()
    if not allow_empty and not s:
        raise ValueError("empty string not allowed")
    return s


def _norm_uploads(v: Any) -> list[Any]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("uploads must be list")
    return v


def _norm_history_item(h: Any) -> dict[str, Any]:
    if not isinstance(h, dict):
        raise ValueError("history item must be object")
    at = _parse_utc(h.get("at"))
    by = _norm_str(h.get("by"), allow_empty=False)
    fr = _norm_str(h.get("from"), allow_empty=False)
    to = _norm_str(h.get("to"), allow_empty=False)
    reason = _norm_str(h.get("reason")) if "reason" in h else None
    out = {"at": at, "by": by, "from": fr, "to": to}
    if reason is not None:
        out["reason"] = reason
    return out


def _norm_history(v: Any) -> list[dict[str, Any]]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("history must be list")
    items = [_norm_history_item(x) for x in v]
    items.sort(key=lambda x: x["at"], reverse=True)
    return items


class Booking(BaseModel):
    def __init__(self, doc: Optional[dict[str, Any]] = None):
        super().__init__(doc or {})

    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        service_id = _norm_str(payload.get("service_id"), allow_empty=False)
        customer_id = _norm_str(payload.get("customer_id"))  # optional at creation
        start_at = _parse_utc(payload.get("start_at"))
        end_at = _parse_utc(payload.get("end_at"))
        policy_agreed_at = _parse_utc(payload.get("policy_agreed_at"))

        doc: dict[str, Any] = {
            "service_id": service_id,
            "customer_id": customer_id,
            "start_at": start_at,
            "end_at": end_at,
            "policy_agreed_at": policy_agreed_at,
            "status": _norm_status(payload.get("status")),
            "source": _norm_source(payload.get("source")),
            "code": _norm_str(payload.get("code")),
            "note_customer": _norm_str(payload.get("note_customer")) or "",
            "note_internal": _norm_str(payload.get("note_internal")) or "",
            "uploads": _norm_uploads(payload.get("uploads")),
            "history": _norm_history(payload.get("history")),
            "reschedule_of": _norm_str(payload.get("reschedule_of")),
            "canceled_reason": _norm_str(payload.get("canceled_reason")),
        }
        return Booking.stamp_new(doc)

    @staticmethod
    def prepare_update(partial: dict[str, Any]) -> dict[str, Any]:
        upd: dict[str, Any] = {}

        if "service_id" in partial:
            upd["service_id"] = _norm_str(partial.get("service_id"), allow_empty=False)

        if "customer_id" in partial:
            upd["customer_id"] = _norm_str(partial.get("customer_id"))

        if "start_at" in partial:
            upd["start_at"] = _parse_utc(partial.get("start_at"))

        if "end_at" in partial:
            upd["end_at"] = _parse_utc(partial.get("end_at"))

        if "policy_agreed_at" in partial:
            upd["policy_agreed_at"] = _parse_utc(partial.get("policy_agreed_at"))

        if "status" in partial:
            upd["status"] = _norm_status(partial.get("status"))

        if "source" in partial:
            upd["source"] = _norm_source(partial.get("source"))

        if "code" in partial:
            upd["code"] = _norm_str(partial.get("code"))

        if "note_customer" in partial:
            upd["note_customer"] = _norm_str(partial.get("note_customer")) or ""

        if "note_internal" in partial:
            upd["note_internal"] = _norm_str(partial.get("note_internal")) or ""

        if "uploads" in partial:
            upd["uploads"] = _norm_uploads(partial.get("uploads"))

        if "history" in partial:
            upd["history"] = _norm_history(partial.get("history"))

        if "reschedule_of" in partial:
            upd["reschedule_of"] = _norm_str(partial.get("reschedule_of"))

        if "canceled_reason" in partial:
            upd["canceled_reason"] = _norm_str(partial.get("canceled_reason"))

        return Booking.stamp_update(upd)

    def to_dict(self, fields: Optional[list[str]] = None) -> dict[str, Any]:
        d = super().to_dict(fields)
        for k in ("start_at", "end_at", "policy_agreed_at"):
            if k in self._doc and (fields is None or k in d):
                d[k] = iso(_parse_utc(self._doc[k]))
        if "history" in self._doc and (fields is None or "history" in d):
            out_hist: list[dict[str, Any]] = []
            for h in self._doc.get("history", []) or []:
                at = iso(_parse_utc(h["at"]))
                item = {**h, "at": at}
                out_hist.append(item)
            d["history"] = out_hist
        return d

    @staticmethod
    def append_history(existing: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
        hist = existing.get("history") or []
        hist.append(_norm_history_item(entry))
        hist.sort(key=lambda x: x["at"], reverse=True)
        return {"history": hist}
