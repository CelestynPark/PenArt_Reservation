from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app.core.constants import ErrorCode, ReviewStatus, REVIEW_WINDOW_DAYS_DEFAULT
from app.repositories import review as review_repo
from app.repositories import booking as booking_repo
from app.repositories.common import get_collection, in_txn, map_pymongo_error
from app.utils.time import now_utc, isoformat_utc


__all__ = ["can_write", "create", "update", "basic_spam_check"]


class ServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def _ok_bool(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def _err_from_repo(e: Exception) -> ServiceError:
    if isinstance(e, (review_repo.RepoError, booking_repo.RepoError)):
        return ServiceError(e.code, e.message)  # type: ignore[attr-defined]
    return ServiceError(ErrorCode.ERR_INTERNAL.value, "internal error")


def _parse_iso_utc(s: str) -> datetime:
    if not isinstance(s, str) or not s:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "invalid datetime")
    try:
        if s.endswith("Z"):
            base = datetime.fromisoformat(s[:-1])
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            else:
                base = base.astimezone(timezone.utc)
        else:
            base = datetime.fromisoformat(s)
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            else:
                base = base.astimezone(timezone.utc)
        return base
    except Exception as e:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "invalid datetime") from e
    

def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _window_days() -> int:
    return int(REVIEW_WINDOW_DAYS_DEFAULT)


def _pick_text(i18n: Any) -> str:
    if not isinstance(i18n, dict):
        return ""
    return str(i18n.get("ko") or i18n.get("en") or "").strip()


# --------- Spam -----------------------------------------------------------


_BANNED_PATTERNS = [
    r"(?i)\bhttps?://", # links
    r"(?i)\b무료\b",
    r"(?i)\b성인\b",
    r"(?i)\b카지노\b",
    r"(?i)\bbitcoin\b",
    r"(?i)\bloan\b"
]
_RE_BANNED = [re.compile(p) for p in _BANNED_PATTERNS]
_RE_REPEAT = re.compile(r"(.)\1{4,}")   # same char 5+ in a row
_MIN_TEXT_LEN = 5


def basic_spam_check(text: str) -> Dict[str, Any]:
    t = (text or "").strip()
    if len(t) < _MIN_TEXT_LEN:
        return {"passed": False, "reason": "too_short"}
    if _RE_REPEAT.search(t):
        return {"passed": False, "reason": "repeated_chars"}
    for rgx in _RE_BANNED:
        if rgx.search(t):
            return {"passed": False, "reason": "banned_phrase"}
    return {"passed": True}


# --------- Policy / Eligibility -----------------------------------------------------------


def _eligible_by_status_and_window(booking: Dict[str, Any], now_iso: Optional[str]) -> tuple[bool, str | None]:
    if not isinstance(booking, dict):
        return False, "not_found"
    if str(booking.get("status")) != "completed":
        return False, "not_completed"
    end_at = booking.get("end_at")
    if not isinstance(end_at, str) or not end_at:
        return False, "invalid_end_at"
    end_dt = _parse_iso_utc(end_at)
    now_dt = _parse_iso_utc(now_iso) if isinstance(now_iso, str) and now_iso else now_utc()
    if now_dt < end_dt:
        return False, "not_yet"
    window_end = end_dt + timedelta(days=_window_days())
    if now_dt > window_end:
        return False, "window_closed"
    return True, None


def can_write(booking_id: str, now_utc: str | None = None) -> Dict[str, Any]:
    try:
        bk = booking_repo.find_by_id(booking_id)
        if not bk:
            return _ok_bool({"allowed": False, "reason": "not_found"})
        allowed, reason = _eligible_by_status_and_window(bk, now_utc)
        return _ok_bool({"allowed": allowed, "reason": reason})
    except booking_repo.RepoError as e:
        raise _err_from_repo(e)
    

# --------- Create / Update -----------------------------------------------------------


def _require_rating(val: Any) -> int:
    try:
        r = int(val)
    except Exception as e:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "rating must be integer") from e
    if r < 1 or r > 5:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "rating must be between 1 and 5")
    return r


def _require_i18n(obj: Any, key: str) -> Dict[str, str]:
    if not isinstance(obj, dict):
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, f"{key} must be object")
    out: Dict[str, str] = {}
    for k in ("ko", "en"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    if not out:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, f"{key} empty")
    return out


def _validate_buyer(review_payload: Dict[str, Any], booking: Dict[str, Any]) -> None:
    pid = review_payload.get("customer_id")
    if not pid:
        raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, "customer_id required")
    if str(booking.get("customer_id")) != str(pid):
        raise ServiceError (ErrorCode.ERR_FORBIDDEN.value, "now_booking_owner")
    

def create(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "payload must be dict")
    
    booking_id = (payload.get("booking_id") or "").strip()
    if not booking_id:
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "booking_id requried")
    
    try:
        bk = booking_repo.find_by_id(booking_id)
        if not bk:
            raise ServiceError(ErrorCode.ERR_NOT_FOUND.value, "booking not found")
        
        allowed, reason = _eligible_by_status_and_window(bk, None)
        if not allowed:
            raise ServiceError(ErrorCode.ERR_POLICY_CUTOFF.value, reason or "now_allowed")
        
        _validate_buyer(payload, bk)

        rating = _require_rating(payload.get("rating"))
        quote_i18n = _require_i18n(payload.get("quote_i18n"), "quote_i18n")
        comment_i18n = payload.get("comment_i18n") or {}
        if isinstance(comment_i18n, dict) or comment_i18n:
            txt = _pick_text(comment_i18n)
        else:
            txt = _pick_text(quote_i18n)
        
        spam = basic_spam_check(txt)
        if not spam.get("passed", False):
            raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, f"spam_{spam.get('reason')}")
        
        doc = {
            "booking_id": bk["_id"],
            "customer_id": payload.get("customer_id"),
            "rating": rating,
            "quote_i18n": quote_i18n,
            "comment_i18n": comment_i18n if isinstance(comment_i18n, dict) else {},
            "status": ReviewStatus.published.value
        }

        created = review_repo.create_review(doc)
        return _ok(created)
    except (review_repo.RepoError, booking_repo.RepoError) as e:
        raise _err_from_repo(e)
    

def update(review_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(review_id, str) or not review_id.strip():
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "review_id required")
    if not isinstance(payload, dict):
        raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "payload must be dict")
    
    try:
        rv = review_repo.find_by_id(review_id)
        if not rv:
            raise ServiceError(ErrorCode.ERR_NOT_FOUND.value, "review not found")
        
        # fetch booking to re-validate window and ownership
        bk_id = str(rv.get("booking_id"))
        bk = booking_repo.find_by_id(bk_id)
        if not bk:
            raise ServiceError(ErrorCode.ERR_NOT_FOUND.value, "booking not found")
        
        _validate_buyer(payload, bk)
        allowed, reason = _eligible_by_status_and_window(bk, None)
        if not allowed:
            raise ServiceError(ErrorCode.ERR_POLICY_CUTOFF.value, reason or "now_allowed")
        
        set_fields: Dict[str, Any] = {}
        if "rating" in payload:
            set_fields["rating"] = _require_rating(payload.get("rating"))
        if "qutoe_i18n" in payload:
            set_fields["quote_i18n"] = _require_i18n(payload.get("quote_i18n"), "quote_i18n")
        if "comment_i18n" in payload:
            ci = payload.get("comment_i18n") or {}
            if not isinstance(ci, dict):
                raise ServiceError(ErrorCode.ERR_INVALID_PAYLOAD.value, "comment_i18n must be object")
            set_fields["comment_i18n"] = {k: v for k, v in ci.items() if isinstance(v, str) and v.strip()}

        if set_fields:
            txt = _pick_text(set_fields.get("comment_i18n") or set_fields.get("quote_i18n") or rv.get("comment_i18n") or rv.get("quote_i18n"))
            spam  = basic_spam_check(txt or "")
            if not spam.get("passed", False):
                raise ServiceError(ErrorCode.ERR_FORBIDDEN.value, f"spam_{spam.get('reason')}")
            
        set_fields["updated_at"] = _now_iso()

        with in_txn(None) as s:
            doc = get_collection("reviews").find_one_and_update(
                {"_id": rv["_id"]},
                {"$set": set_fields},
                return_document=ReturnDocument.AFTER,
                session=s
            )
            if not doc:
                raise ServiceError(ErrorCode.ERR_NOT_FOUND.value, "review not found")
            return _ok(doc)
    except (review_repo.RepoError, booking_repo.RepoError) as e:
        raise _err_from_repo(e)
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise ServiceError(err["code"], err["message"])
    