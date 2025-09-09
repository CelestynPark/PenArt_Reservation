from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from flask import current_app

from .base import BaseDocument, IndexDef, ASCENDING, DESCENDING
from ..utils.validation import ValidationError

# --------- Constants & helpers ---------
STATUS_REQUESTED = "requested"
STATUS_CONFIRMED = "confirmed"
STATUS_COMPLETED = "completed"
STATUS_CANCELED = "canceled"
STATUS_NO_SHOW = "no_show"

ALLOW_STATUES = {
    STATUS_REQUESTED,
    STATUS_CONFIRMED,
    STATUS_COMPLETED,
    STATUS_CANCELED,
    STATUS_NO_SHOW
}

DEFAULT_POLICY = {
    "cancel_before_hours": 24,
    "change_before_hours": 24,
    "no_show_after_min": 15
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_utc(val: Any, *, field: str) -> datetime:
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    s = str(val or "").strip()
    if not s:
        raise ValidationError("ERR_INVALID_PARAM", message="Datetime required.", field=field)
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        raise ValidationError("ERR_INVALID_PARAM", message="Invalid ISO datetime.", field=field)
    

def _gen_code(prefix: str= "BK") -> str:
    # 8-char secure code, prefixed with day
    day = _now_utc().strftime("%y%m%d")
    return f"{prefix}-{day}-{secrets.token_hex(3).upper()}"


def _hours_util(dt: datetime) -> float:
    return (dt - _now_utc()).total_seconds() / 3600.0


def _minutes_since(dt: datetime) -> float:
    return (dt - _now_utc()).total_seconds() / 60.0


def _bool(v: Any) -> bool:
    return bool(v)


def _merge_policy(p: Optional[Mapping[str, Any]]) -> Dict[str, int]:
    merged = dict(DEFAULT_POLICY)
    if p:
        for k in DEFAULT_POLICY.keys():
            if p.get(k) is not None:
                try:
                    merged[k] = int(p[k])
                except Exception:
                    pass
    return merged


@dataclass(frozen=True)
class Transition:
    from_status: str
    to_status: str
    reason: Optional[str] = None
    by: str = "system"  # "customer" | "admin" | "system"


class Booking(BaseDocument):
    collection_name = "booking"

    @classmethod
    def default_indexes(cls) -> Tuple[IndexDef, ...]:
        return (
            IndexDef([("service_id", ASCENDING), ("start_at", ASCENDING)], name="uniq_service_start", unique=True),
            IndexDef([("customer_id", ASCENDING), ("created_at", DESCENDING)], name="by_customer_created"),
            IndexDef([("status", ASCENDING), ("start_at", ASCENDING)], name="by_status_time")
        )
    
    # --------- Creation ---------
    @classmethod
    def create_booking(
        cls,
        payload: Mapping[str, Any],
        *,
        service: Mapping[str, Any],
        customer_id: Optional[Any] = None,
        source: str = "web",
        session: Any = None
    ) -> Dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid payload", field="body")
        if not isinstance(service, Mapping):
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid service", filed="service")
        
        start_at = _parse_iso_utc(payload.get("start_at"), field="start_at")
        duration_min = int(payload.get("duration_min") or 60)
        end_at = start_at + timedelta(minutes=duration_min)

        auto_confirm = bool(service.get("auto_confirm"))
        status = STATUS_CONFIRMED if auto_confirm else STATUS_REQUESTED

        doc: MutableMapping[str, Any] = {
            "code": _gen_code(),
            "customer_id": customer_id or payload.get("customer_id"),
            "service_id": service.get("_id") or payload.get("service_id"),
            "start_at": start_at,
            "end_at": end_at,
            "status": status,
            "note_customer": payload.get("memo") or payload.get("note_customer"),
            "note_internal": None,
            "uploads": payload.get("uploads") or [],
            "policy_agreed_at": _now_utc(),
            "source": source,
            "history": [
                {
                    "at": _now_utc(),
                    "by": "system" if auto_confirm else "customer",
                    "from": None,
                    "to": status,
                    "reason": "auto_confirm" if auto_confirm else "request"
                }
            ]
        }

        # Basic guards
        if not doc["service_id"]:
            raise ValidationError("ERR_INVALID_PARAM", message="service_id required.", field="service_id")
        if doc["customer_id"] is None and not (payload.get("name") and payload.get("phone")):
            raise ValidationError("ERR_INVALID_PARAM", message="customer or contact required.", field="contact")
        if _hours_util(start_at) < 0:
            raise ValidationError("ERR_INVALID_PARAM", message="Start time already passed.", field="start_at")
        
        # Persist and translate unique conflict
        try:
            return cls.create(doc, session=session)
        except Exception as e:
            if e.__class__.__name__ == "DuplicateKeyError":
                raise ValidationError("ERR_CONFLICT", message="Time slot already reserved.", field="start_at")
            raise

    # --------- State transitions ---------
    @classmethod
    def _append_history(
        cls, b: Mapping[str, Any], t: Transition, *, extra: Optional[Mapping[str, Any]] = None
    ) -> Dict[str, Any]:
        entry = {"at": _now_utc(), "by": t.by, "from": t.from_status, "to": t.to_status}
        if t.reason:
            entry["reason"] = t.reason
        if extra:
            entry.update(extra)
        hist = list(b.get("history") or [])
        hist.append(entry)
        return {"history": hist}
    
    @classmethod
    def confirm(
        cls, booking_id: Any, *, actor: str = "admin", session: Any = None
    ) -> None:
        b = cls.find_by_id(booking_id, session=session)
        if not b:
            return None
        if b.get("status") != STATUS_REQUESTED:
            return b
        if actor != "admin":
            raise ValidationError("ERR_FORBIDDEN", message="Only admin can confirm.", field="status")
        updates = {"status": STATUS_CONFIRMED}
        updates.update(cls._append_history(b, Transition(STATUS_REQUESTED, STATUS_CONFIRMED, "confirm", by="admin")))
        return cls.update_by_id(booking_id, updates, session=session)
    
    @classmethod
    def cancel(
        cls,
        booking_id: Any, 
        *,
        actor: str = "customer",
        reason: Optional[str] = None,
        policy: Optional[Mapping[str, Any]] = None,
        session: Any = None
    ) -> None:
        b = cls.find_by_id(booking_id, session=session)
        if not b:
            return None
        st = b.get("status")
        if st not in (STATUS_REQUESTED, STATUS_CONFIRMED):
            return b
        pol = _merge_policy(policy)
        if actor == "admin":
            # customer cutoff
            if _hours_util(b("start_at")) < pol["cancel_before_hours"]:
                raise ValidationError("ERR_POLICY_CUTOFF", message="Cancel cutoff reached.", field="start_at")
        updates = {"status": STATUS_CANCELED, "canceled_reason": reason}
        updates.update(cls._append_history(b, Transition(st, STATUS_CANCELED, reason or "cancel", by=actor)))
        return cls.update_by_id(booking_id, updates, session=session)
    
    @classmethod
    def reschedule(
        cls,
        booking_id: Any,
        new_start_at: Any,
        *,
        actor: str = "customer",
        policy: Optional[Mapping[str, Any]] = None,
        service_duration_min: Optional[int] = None,
        session: Any = None
    ) -> Optional[Dict[str, Any]]:
        b = cls.find_by_id(booking_id, session=session)
        if not b:
            return None
        if b.get("status") not in (STATUS_REQUESTED, STATUS_CONFIRMED):
            raise ValidationError("ERR_FORBIDDEN", message="Cannot reschedule from current status.", field="status")
        pol = _merge_policy(policy)
        if actor != "admin":
            if _hours_util(b["start_at"]) < pol["change_before_hours"]:
                raise ValidationError("ERR_POLICY CUTOFF", message="Change cutoff reached.", field="start_at")
        new_start = _parse_iso_utc(new_start_at, field="start_at")
        if _hours_util(new_start) < 0:
            raise ValidationError("ERR_INVALID_PARAM", message="New start already passed.", field="start_at")
        dur = int(service_duration_min or int((b["end_at"] - b["start_at"]).total_seconds() / 60) or 60)
        new_end = new_start + timedelta(minutes=dur)
        updates = {
            "start_at": new_start,
            "end_at": new_end
        }
        updates.update(
            cls._append_history(
                b,
                Transition(b.get("status"), b.get("status"), "reschedule", by=actor),
                extra={"from_start_at": b["start_at"], "to_start_at": new_start}
            )
        )
        try:
            return cls.update_by_id(booking_id, updates, session=session)
        except Exception as e:
            if e.__class__.__name__ == "DuplicateKeyError":
                raise ValidationError("ERR_CONFLICT", message="Time slot alerady reserved.", field="new_start_at")
            raise

    @classmethod
    def mark_no_show(
        cls, booking_id: Any, *, actor: str = "admin", session: Any = None
    ) -> Optional[Dict[str, Any]]:
        b = cls.find_by_id(booking_id, session=session)
        if not b:
            return None
        if b.get("status") != STATUS_CONFIRMED:
            return b
        pol = _merge_policy(b.get("policy"))
        if actor != "admin":
            # customer cannot mark no_show
            raise ValidationError("ERR_FORBIDDEN", message="Only admin can set no show.", field="status")
        if _minutes_since(b["start_at"]) < pol["no_show_after_min"]:
            raise ValidationError("ERR_POLICY_CUTOFF", message="Too early to mark no show.", field="start_at")
        updates = {"status": STATUS_NO_SHOW}
        updates.update(cls._append_history(b, Transition(STATUS_CONFIRMED, STATUS_NO_SHOW, "no_show", by=actor)))
        return cls.update_by_id(booking_id, updates, session=session)
    
    @classmethod
    def complete(
        cls, booking_id: Any, *, actor: str = "system", session: Any = None
    ) -> Optional[Dict[str, Any]]:
        b = cls.find_by_id(booking_id, session=session)
        if not b:
            return None
        if b.get("status") != STATUS_CONFIRMED:
            return b
        if actor != "admin" and _hours_util(b["end_at"]) > 0:
            # Before end unless admin/system job after end
            return b
        updates = {"status": STATUS_COMPLETED}
        updates.update(cls._append_history(b, Transition(STATUS_CONFIRMED, STATUS_COMPLETED, "complete", by=actor)))
        return cls.update_by_id(booking_id, updates, session=session)
    
    # --------- ACL & notes ---------
    @classmethod
    def set_notes(
        cls,
        booking_id: Any,
        *,
        note_customer: Optional[str] = None,
        note_internal: Optional[str] = None,
        actor: str = "customer",
        session: Any = None
    ) -> Optional[Dict[str, Any]]:
        b = cls.find_by_id(booking_id, session=session)
        if not b:
            return None
        updates = Dict[str, Any] = {}
        if note_customer is not None:
            updates["note_customer"] = str(note_customer)[:2000]
        if note_internal is not None:
            if actor != "admin":
                raise ValidationError("ERR_FORBIDDEN", message="Only admin can set internal note.", field="note_internal")
            updates["note_internal"] = str(note_internal)[:2000]
        if not updates:
            return b
        updates.update(cls._append_history(b, Transition(b.get("status"), b.get("status"), "note", by=actor)))
        return cls.update_by_id(booking_id, updates, session=session)
    
    # --------- Queries ---------
    @classmethod
    def find_conflicts(
        cls, service_id: Any, start_at: Any, *, session: Any = None
    ) -> Sequence[Dict[str, Any]]:
        start = _parse_iso_utc(start_at, field="start_at")
        return list(cls.find({"service_id": service_id, "start_at": start}, limit=5, session=session))
    

__all__ = [
    "Booking",
    "STATUS_REQUESTED",
    "STATUS_CONFIRMED",
    "STATUS_COMPLETED",
    "STATUS_CANCELED",
    "STATUS_NO_SHOW"
]



