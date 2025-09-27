from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.core.constants import ErrorCode, BookingStatus
from app.repositories import booking as booking_repo
from app.utils.time import to_utc, isoformat_utc
from app.services import availability_service as avail_svc


__all__ = [
    "create_request",
    "transition",
    "check_cutoff",
    "append_history"
]


#------------------------------------
# Errors
#------------------------------------
class ServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


#------------------------------------
# Utils
#------------------------------------
def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_policy(booking: Dict[str, Any]) -> Dict[str, int]:
    p = booking.get("policy") or {}
    return {
        "cancel_before_hours": int(p.get("cancel_before_hours") or 0),
        "change_before_hours": int(p.get("change_before_hours") or 0),
        "no_show_after_min": int(p.get("no_show_after_min") or 0)
    }


def _parse_dt_utc(s: str) -> datetime:
    try:
        return to_utc(s)
    except Exception as e:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "invalid ISO8601 datetime") from e
    

def _ensure_slot_free(service_id: str, start_at: str, end_at: str) -> None:
    ok = avail_svc.is_slot_available(service_id, start_at, end_at)
    if not ok:
        raise ServiceError(ErrorCode.ERR_CONFLICT.value, "slot is not available")
    

#------------------------------------
# Public API
#------------------------------------
def create_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a booking in 'requested' state.
    Required: service_id, start_at(UTC ISO8601), name/phone (validated at API layer), agree:true
    """
    try:
        doc = dict(payload or {})
        svc_id = doc.get("service_id")
        start_at = doc.get("start_at")
        if not isinstance(svc_id, str) or not svc_id.strip():
            raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "service_id is required")
        if not isinstance(start_at, str) or not start_at.strip():
            raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "start_at is required")
    
        # Normalize datetimes
        s_utc = _parse_dt_utc(start_at)
        doc["start_at"] = isoformat_utc(s_utc)

        # Determine end_at if given (else repo computes)
        if isinstance(doc.get("end_at"), str) and doc["end_at"].strip():
            e_utc = _parse_dt_utc(doc["end_at"])
            doc["end_at"] = isoformat_utc(e_utc)

        # Pre-check slot availability (best-effort; uniqueness at DB enforces too)
        e_iso = doc.get("end_at")
        if e_iso:
            _ensure_slot_free(svc_id, doc["start_at"], e_iso)

        # Force initial status
        doc["status"] = BookingStatus.requested.value

        created = booking_repo.create_booking(doc)
        return {"ok": True, "data": created}
    except booking_repo.RepoError as e:
        code = e.code or ErrorCode.ERR_INTERNAL.value
        msg = "booking conflict" if code == ErrorCode.ERR_CONFLICT.value else e.message
        raise ServiceError(code, msg) from e
    

def transition(booking_id: str, action: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Supported actions: "confirm" | "cancel" | "complete" | "no_show" | "reschedule"
    """
    meta = dict(meta or {})
    b = booking_repo.find_by_id(booking_id)
    if not b:
        raise ServiceError(ErrorCode.ERR_NOT_FOUND.value, "booking not found")
    
    status = b.get("status")
    svc_id = b.get("service_id")
    start_at = b.get("start_at")
    end_at = b.get("end_at")

    # Common policy checks
    policy_err = check_cutoff(b, action)
    if policy_err:
        raise ServiceError(policy_err["code"], policy_err["message"])
    
    # State transitions
    if action == "confirm":
        if status != BookingStatus.requested.value:
            raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, "only requested can be confirmed")
        try:
            updated = booking_repo.transition(
                booking_id,
                from_status=BookingStatus.requested.value,
                to_status=BookingStatus.confirmed.value,
                by=meta.get("by") or {},
                reason=meta.get("reason")
            )
            return {"ok": True, "data": updated}
        except booking_repo.RepoError as e:
            raise ServiceError(e.code, e.message) from e
        
    if action == "cancel":
        if status not in (BookingStatus.requested.value, BookingStatus.confirmed.value):
            raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, "only requested/confirmed can be canceled")
        try:
            updated = booking_repo.transition(
                booking_id,
                from_status=status,
                to_status=BookingStatus.canceled.value,
                by=meta.get("by") or {},
                reason=meta.get("reason")  
            )
            return {"ok": True, "data": updated}
        except booking_repo.RepoError as e:
            raise ServiceError(e.code, e.message) from e 
        
    if action == "complete":
        if status != BookingStatus.confirmed.value:
            raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, "only confirmed can be completed")
        # must be past end_at
        if isinstance(end_at, str) and _parse_dt_utc(end_at) > _now_utc():
            raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, "cannot complete before session ends")
        try:
            updated = booking_repo.transition(
                booking_id,
                from_status=BookingStatus.confirmed.value,
                to_status=BookingStatus.completed.value,
                by=meta.get("by") or {},
                reason=meta.get("reason")  
            )
            return {"ok": True, "data": updated}
        except booking_repo.RepoError as e:
            raise ServiceError(e.code, e.message) from e 
        
    if action == "no_show":
        if status != BookingStatus.confirmed.value:
            raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, "only confirmed can be marked no_show")
        # must be past start_at + no_show_after_min
        pol = _get_policy(b)
        threshold = _parse_dt_utc(start_at) + timedelta(minutes=pol["no_show_after_min"])
        if _now_utc() < threshold:
            raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, "too early to mark no_show")
        try:
            updated = booking_repo.transition(
                booking_id,
                from_status=BookingStatus.confirmed.value,
                to_status=BookingStatus.no_show.value,
                by=meta.get("by") or {},
                reason=meta.get("reason")  
            )
            return {"ok": True, "data": updated}
        except booking_repo.RepoError as e:
            raise ServiceError(e.code, e.message) from e 
        
    if action == "reschedule":
        if status not in (BookingStatus.requested.value, BookingStatus.confirmed.value):
            raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, "only requested/confirmed can be rescheduled")
        new_start = meta.get("new_start_at")
        if not isinstance(new_start, str) or not new_start.strip():
            raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD, "new_start_at is required")
        new_start_dt = _parse_dt_utc(new_start)

        # compute new end_at:
        # prefer original duration based on existing end_at
        if not isinstance(end_at, str) or not end_at.strip():
            raise ServiceError(ErrorCode.ERR_INTERNAL.value, "booking missing end_at")
        dur = _parse_dt_utc(end_at) - _parse_dt_utc(start_at)
        new_end_dt = new_start_dt + dur

        # slot availability
        _ensure_slot_free(svc_id, isoformat_utc(new_start_dt), isoformat_utc(new_end_dt))

        # Impletment reschedule as: create new booking (requested) -> cancel old (reason=reschedule)
        # This avoids changing 'start_at' which repository transition restricts.
        new_doc = {
            "service_id": svc_id,
            "customer_id": b.get("customer_id"),
            "start_at": isoformat_utc(new_start_dt),
            "end_at": isoformat_utc(new_end_dt),
            "status": BookingStatus.requested.value if status == BookingStatus.requested.value else BookingStatus.confirmed.value,
            "note_customer": b.get("note_customer"),
            "note_internal": b.get("note_internal"),
            "policy": b.get("policy"),
            "source": b.get("source"),
            "reschedule_of": str(b.get("_id")),
            "history": (b.get("history") or [])
        }
        try:
            created = booking_repo.create_booking(new_doc)
        except booking_repo.RepoError as e:
            raise ServiceError(e.code, e.message) from e
        
        # Cancel original
        try:
            booking_repo.transition(
                booking_id,
                from_status=status,
                to_status=BookingStatus.canceled.value,
                by=meta.get("by") or {},
                reason=meta.get("reason") or "reschedule"
            )
        except booking_repo.RepoError:
            # If cancel fails, we still return the new booking (caller can reconcile)
            pass

        return {"ok": True, "data": created}
    
    raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "unsupported action")


def check_cutoff(booking: Dict[str, Any], action: str, now_utc: Optional[str] = None) -> Optional[Dict[str, str]]:
    """
    Return NOen if allowed; else returns {"code": ..., "message": ...}
    Policy times are evaluated in UTC.
    """
    policy = _get_policy(booking)
    now = _parse_dt_utc(now_utc) if isinstance(now_utc, str) else _now_utc()

    start_dt = _parse_dt_utc(booking.get("start_at"))
    end_dt = _parse_dt_utc(booking.get("end_at")) if booking.get("end_at") else start_dt

    if action == "cancel":
        cutoff = start_dt - timedelta(hours=policy["cancel_before_hours"])
        if now > cutoff:
            return {"code": ErrorCode.ERR_POLICY_CUTOFF.value, "message": "cancel cutoff passed"}
        return None
    
    if action in ("reschedule",):
        cutoff = start_dt - timedelta(hours=policy["cancel_before_hours"])
        if now > cutoff:
            return {"code": ErrorCode.ERR_POLICY_CUTOFF.value, "message": "change cutoff passed"}
        return None
    
    if action == "complete":
        if now < end_dt:
            return {"code": ErrorCode.ERR_FORBIDDEN.value, "message": "cannot complete before end time"}
        return None
    
    if action == "no_show":
        threshold = start_dt + timedelta(minutes=policy["no_show_after_min"])
        if now < threshold:
            return {"code": ErrorCode.ERR_FORBIDDEN.value, "message": "too early to mark no_show"}
        return None
    
    if action == "confirm":
        return None
    
    return {"code": ErrorCode.ERR_INVALID_PAYLOAD.value, "message": "unsupported action"}


def append_history(booking_id: str, by: str, from_: str, to: str, reason: Optional[str] = None) -> None:
    ev = {"by": by, "from": from_, "to": to}
    if reason:
        ev["reason"] = reason
    ok = booking_repo.append_history(booking_id, ev)
    if not ok:
        raise ServiceError(ErrorCode.ERR_INTERNAL.value, "failed to append history")
    
        