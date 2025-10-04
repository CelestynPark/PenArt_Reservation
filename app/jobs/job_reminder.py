from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.config import load_config
from app.core.constants import BookingStatus, ErrorCode
from app.models import job_locks
from app.repositories import booking as booking_repo
from app.services import metrics_service, notify_service
from app.utils.time import isoformat_utc

__all__ = ["run_job_reminder"]

# ----------------------------
# Helpers 
# ----------------------------

def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return{"ok": True, "data": data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _hour_floor(dt: datetime) -> datetime:
    dt = _as_utc(dt)
    return datetime(dt.year, dt.month, dt.day, dt.hour, tzinfo=timezone.utc)


def _reminder_window(now_utc: datetime, hours_before: int) -> Tuple[str, str, datetime]:
    """
    Returns (start_iso, end_iso, hour_anchor) for bookings starting within the hour window
    that is exactly `hours_before` ahead of now_utc.
    """
    target = _as_utc(now_utc) + timedelta(hours=int(hours_before))
    anchor = _hour_floor(target)
    start = anchor
    end = anchor + timedelta(hours=1)
    return isoformat_utc(start), isoformat_utc(end), anchor


def _lock_key(anchor: datetime) -> str:
    return f"job:reminder:{anchor.strftime('%Y-%m-%dT%H')}"


def _extract_contacts(b: Dict[str, Any]) -> Dict[str, Optional[str]]:
    """
    Booking payloads are expected to include name/phone (API layer validated).
    Email may exist via linked customer. Use best-effort fields commonly present.
    """
    phone = b.get("phone") or (b.get("buyer") or {}).get("phone")
    email = b.get("email") or (b.get("buyer") or {}).get("email")
    return {"phone": phone, "email": email}


def _eligible(b: Dict[str, Any]) -> bool:
    if (b.get("status") or "") != BookingStatus.confirmed.value:
        return False
    # Skip if reminder already sent (idempotency)
    r = b.get("reminder") or {}
    if r.get("sent_at"):
        return False
    return True


def _send_for_booking(
    booking: Dict[str, Any],
    channels: List[str],
    lang: str
) -> bool:
    """
    Sends reminder over allowed channels. Returns True if at least one channel succeeded.
    """
    contacts = _extract_contacts(booking)
    start_at = booking.get("start_at")
    code = booking.get("code")
    payload = {"start_at": start_at, "code": code, "name": booking.get("name")}
    succeeded = False

    for ch in channels:
        ch = (ch or "").strip().lower()
        to: Optional[str] = None

        if ch == "email":
            to = contacts.get("email")
        elif ch in ("sms", "kakao"):
            to = contacts.get("phone")
        
        if not to:
            continue    # contact missing for this channel

        res = notify_service.send(
            {
                "to": to,
                "channel": ch,
                "template": "booking_reminder",
                "payload": payload,
                "lang": lang
            }
        )
        if res.get("ok"):
            succeeded = True
    
    return succeeded


def _mark_reminded(booking_id: Any, when_utc: datetime) -> None:
    try:
        # Repository method contract: set reminder.sent_at (ISO UTC) if not already set.
        booking_repo.mark_reminded(booking_id, isoformat_utc(_as_utc(when_utc)))
    except Exception:
        # Logging/metrics would be handled elsewhere; do not break job flow.
        pass


# ----------------------------
# Public entrypoint 
# ----------------------------

def run_job_reminder(now_utc: datetime) -> Dict[str, Any]:
    """
    Triggers reminders REMINDER_BEFORE_HOURS prior to booking start.
    Idempotent per hour-window via job lock and per-booking 'reminder.send_at'.
    """
    try:
        cfg = load_config()
        hours_before = int(getattr(cfg, "reminder_before_hours", None) or 24)
        start_iso, end_iso, anchor = _reminder_window(now_utc, hours_before)

        # Acquire hour-window lock to avoid duplicate processing across instances 
        key = _lock_key(anchor)
        owner = "job_reminder"
        # TTL: slightly less than an hour to match the window; 50 minutes is safe.
        if not job_locks.acquire_lock(key, owner, ttl_sec=50 * 60):
            return _ok({"sent": 0, "skipped": 0})\
        
        # Fetch candidate bookings within window
        try:
            # Contracts: repository returns bookings with fields used above.
            candidates: Optional[List[Dict[str, Any]]] = booking_repo.find_for_reminder(start_iso, end_iso)
        except booking_repo.RepoError as e:
            # Release lock early on fatal repo error
            job_locks.release_lock(key, owner)
            return _err(e.code or ErrorCode.ERR_INTERNAL.value, e.message or "repository error")
        
        sent_count = 0
        skipped_count = 0

        allowed_channels: List[str] = list(getattr(cfg, "alert_channels", []) or [])
        default_lang = (getattr(cfg, "default_lang", "ko") or "ko").strip().lower()

        for b in candidates or []:
            if not _eligible(b):
                skipped_count += 1
                continue

            lang = (b.get("lang") or b.get("lang_pref") or default_lang).strip().lower()

            if _send_for_booking(b, allowed_channels, lang):
                sent_count += 1
                _mark_reminded(b.get("_id") or b.get("id"), now_utc)
                # Soft metrics ingest; ignore failures
                try:
                    metrics_service.ingest(
                        {
                            "type": "bookings.reminded",
                            "timestamp": isoformat_utc(_as_utc(now_utc)),
                            "meta": {"booking_id": str(b.get("_id") or b.get("id") or "")}
                        }
                    )
                except Exception:
                    pass
                else:
                    skipped_count += 1  # no channel succeeded or not reachable contact
                
        # Release lock after processing
        job_locks.release_lock(key, owner)
        return _ok({"sent": int(sent_count), "skipped": int(skipped_count)})
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))