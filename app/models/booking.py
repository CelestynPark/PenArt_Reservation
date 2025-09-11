from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId

from app.core.constants import BookingStatus, Source, BOOKING_PREFIX
from app.models.base import BaseModel, _coerce_dt, _coerce_id
from app.utils.time import to_iso8601

_CODE_RE = re.compile(rf"^{BOOKING_PREFIX}-\d{{8}}-[A-Za-z0-9]{{6}}$")


def _coerce_status(v: Any) -> str:
    if isinstance(v, BookingStatus):
        return v.value
    if isinstance(v, str) and v in {e.value for e in BookingStatus}:
        return v
    if v is None:
        return BookingStatus.requested.value
    raise ValueError("invalid booking status")


def _coerce_source(v: Any) -> str:
    if isinstance(v, Source):
        return v.value
    if isinstance(v, str) and v in {e.value for e in Source}:
        return v
    if v is None:
        return Source.web.value
    raise ValueError("invalid source")


def _coerce_code(v: Any) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise ValueError("code must be a non-empty string")
    if not _CODE_RE.fullmatch(v):
        # allow only well-formed codes; generation happens elsewhere
        raise ValueError("code format invalid")
    return v


def _coerce_uploads(v: Any) -> List[Dict[str, Any]]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("uploads must be a list")
    out: List[Dict[str, Any]] = []
    for i, it in enumerate(v):
        if isinstance(it, str):
            url = it.strip()
            if not url:
                raise ValueError(f"uploads[{i}] url empty")
            out.append({"url": url})
        elif isinstance(it, dict):
            url = it.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValueError(f"uploads[{i}].url required")
            item: Dict[str, Any] = {"url": url.strip()}
            # pass-through optional fields if provided (e.g., content_type, size)
            for extra in ("content_type", "size", "name"):
                if extra in it:
                    item[extra] = it[extra]
            out.append(item)
        else:
            raise ValueError("uploads items must be string or object")
    return out


def _coerce_history(v: Any) -> List[Dict[str, Any]]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("history must be a list")
    out: List[Dict[str, Any]] = []
    valid_status = {e.value for e in BookingStatus}
    for i, it in enumerate(v):
        if not isinstance(it, dict):
            raise ValueError("history[] must be objects")
        at = _coerce_dt(it.get("at"))
        by = it.get("by")
        if by is not None and not isinstance(by, (str, dict)):
            raise ValueError(f"history[{i}].by must be string/object")
        frm = it.get("from")
        to = it.get("to")
        if frm is not None and frm not in valid_status:
            raise ValueError(f"history[{i}].from invalid")
        if to is not None and to not in valid_status:
            raise ValueError(f"history[{i}].to invalid")
        reason = it.get("reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError(f"history[{i}].reason must be string")
        out.append(
            {
                "at": at,
                "by": by,
                "from": frm,
                "to": to,
                "reason": reason,
            }
        )
    return out


class Booking(BaseModel):
    __collection__ = "bookings"

    code: Optional[str]
    customer_id: Optional[ObjectId]
    service_id: Optional[ObjectId]
    start_at: datetime
    end_at: datetime
    status: str
    note_customer: Optional[str]
    note_internal: Optional[str]
    uploads: List[Dict[str, Any]]
    policy_agreed_at: datetime
    source: str
    history: List[Dict[str, Any]]
    reschedule_of: Optional[ObjectId]
    canceled_reason: Optional[str]

    def __init__(
        self,
        *,
        id: ObjectId | str | None = None,
        code: Optional[str] = None,
        customer_id: ObjectId | str | None = None,
        service_id: ObjectId | str | None = None,
        start_at: datetime | str,
        end_at: datetime | str,
        status: BookingStatus | str | None = None,
        note_customer: Optional[str] = None,
        note_internal: Optional[str] = None,
        uploads: Optional[List[Dict[str, Any] | str]] = None,
        policy_agreed_at: datetime | str,
        source: Source | str | None = None,
        history: Optional[List[Dict[str, Any]]] = None,
        reschedule_of: ObjectId | str | None = None,
        canceled_reason: Optional[str] = None,
        created_at: datetime | str | None = None,
        updated_at: datetime | str | None = None,
    ) -> None:
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)

        if policy_agreed_at is None:
            raise ValueError("policy_agreed_at is required")
        self.policy_agreed_at = _coerce_dt(policy_agreed_at)

        self.start_at = _coerce_dt(start_at)
        self.end_at = _coerce_dt(end_at)
        if self.end_at < self.start_at:
            raise ValueError("end_at must be >= start_at")

        self.code = _coerce_code(code)
        self.customer_id = _coerce_id(customer_id)
        self.service_id = _coerce_id(service_id)
        if self.service_id is None:
            raise ValueError("service_id is required")

        self.status = _coerce_status(status)
        self.note_customer = note_customer if (note_customer is None or isinstance(note_customer, str)) else str(note_customer)
        self.note_internal = note_internal if (note_internal is None or isinstance(note_internal, str)) else str(note_internal)
        self.uploads = _coerce_uploads(uploads)
        self.source = _coerce_source(source)
        self.history = _coerce_history(history)
        self.reschedule_of = _coerce_id(reschedule_of)
        self.canceled_reason = canceled_reason

    def to_dict(self, exclude_none: bool = True) -> Dict[str, Any]:
        base = super().to_dict(exclude_none=exclude_none)
        out: Dict[str, Any] = {
            **base,
            "code": self.code,
            "customer_id": str(self.customer_id) if self.customer_id else None,
            "service_id": str(self.service_id) if self.service_id else None,
            "start_at": to_iso8601(self.start_at),
            "end_at": to_iso8601(self.end_at),
            "status": self.status,
            "note_customer": self.note_customer,
            "note_internal": self.note_internal,
            "uploads": list(self.uploads),
            "policy_agreed_at": to_iso8601(self.policy_agreed_at),
            "source": self.source,
            "history": [
                {
                    "at": to_iso8601(h["at"]),
                    "by": h.get("by"),
                    "from": h.get("from"),
                    "to": h.get("to"),
                    "reason": h.get("reason"),
                }
                for h in self.history
            ],
            "reschedule_of": str(self.reschedule_of) if self.reschedule_of else None,
            "canceled_reason": self.canceled_reason,
        }
        if exclude_none:
            out = {k: v for k, v in out.items() if v is not None}
        return out

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Booking":
        obj: "Booking" = cls.__new__(cls)  # type: ignore[call-arg]
        # Base fields
        setattr(obj, "id", _coerce_id(d.get("_id", d.get("id"))))
        setattr(obj, "created_at", _coerce_dt(d.get("created_at")))
        setattr(obj, "updated_at", _coerce_dt(d.get("updated_at"), getattr(obj, "created_at")))

        # Required times
        setattr(obj, "start_at", _coerce_dt(d.get("start_at")))
        setattr(obj, "end_at", _coerce_dt(d.get("end_at")))
        if obj.end_at < obj.start_at:
            raise ValueError("end_at must be >= start_at")

        # Simple fields
        setattr(obj, "code", _coerce_code(d.get("code")))
        setattr(obj, "customer_id", _coerce_id(d.get("customer_id")))
        setattr(obj, "service_id", _coerce_id(d.get("service_id")))

        setattr(obj, "status", _coerce_status(d.get("status")))
        setattr(obj, "note_customer", d.get("note_customer"))
        setattr(obj, "note_internal", d.get("note_internal"))
        setattr(obj, "uploads", _coerce_uploads(d.get("uploads")))
        setattr(obj, "policy_agreed_at", _coerce_dt(d.get("policy_agreed_at")))
        setattr(obj, "source", _coerce_source(d.get("source")))
        setattr(obj, "history", _coerce_history(d.get("history")))
        setattr(obj, "reschedule_of", _coerce_id(d.get("reschedule_of")))
        setattr(obj, "canceled_reason", d.get("canceled_reason"))
        return obj
