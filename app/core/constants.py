from __future__ import annotations

from enum import StrEnum


# ---- Enumerations (API-visible; must match spec exactly) ----
class BookingStatus(StrEnum):
    requested = "requested"
    confirmed = "confirmed"
    completed = "completed"
    canceled = "canceled"
    no_show = "no_show"


class OrderStatus(StrEnum):
    created = "created"
    awaiting_deposit = "awaiting_deposit"
    paid = "paid"
    canceled = "canceled"
    expired = "expired"


class GoodsStatus(StrEnum):
    draft = "draft"
    published = "published"


class ReviewStatus(StrEnum):
    published = "published"
    hidden = "hidden"
    flagged = "flagged"


class Channel(StrEnum):
    email = "email"
    sms = "sms"
    kakao = "kakao"


class Source(StrEnum):
    web = "web"
    admin = "admin"
    kakao = "kakao"


class ErrorCode(StrEnum):
    ERR_INVALID_PAYLOAD = "ERR_INVALID_PAYLOAD"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_CONFLICT = "ERR_CONFLICT"
    ERR_POLICY_CUTOFF = "ERR_POLICY_CUTOFF"
    ERR_RATE_LIMIT = "ERR_RATE_LIMIT"
    ERR_SLOT_BLOCKED = "ERR_SLOT_BLOCKED"
    ERR_INTERNAL = "ERR_INTERNAL"


# ---- Pagination (global) ----
DEFAULT_PAGE_SIZE: int = 20
MAX_PAGE_SIZE: int = 100
MIN_PAGE_SIZE: int = 1


# ---- Identifiers / Codes ----
BOOKING_CODE_PREFIX = "BKG"
ORDER_CODE_PREFIX = "ORD"
CODE_DATE_FMT = "%Y%m%d"  # for BKG/ORD codes
CODE_BASE36_LEN = 6


# ---- Domain defaults (non-ENV) ----
REVIEW_WINDOW_DAYS_DEFAULT: int = 30  # review creation window after completion


# ---- Security / Headers (defaults) ----
DEFAULT_CSP_POLICY = (
    "default-src 'self'; "
    "img-src 'self' data: blob:; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'"
)


# ---- API response keys (shape reference) ----
API_OK_KEY = "ok"
API_DATA_KEY = "data"
API_ERROR_KEY = "error"
API_I18N_KEY = "i18n"


__all__ = [
    # Enums
    "BookingStatus",
    "OrderStatus",
    "GoodsStatus",
    "ReviewStatus",
    "Channel",
    "Source",
    "ErrorCode",
    # Pagination
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MIN_PAGE_SIZE",
    # Codes
    "BOOKING_CODE_PREFIX",
    "ORDER_CODE_PREFIX",
    "CODE_DATE_FMT",
    "CODE_BASE36_LEN",
    # Domain defaults
    "REVIEW_WINDOW_DAYS_DEFAULT",
    # Security
    "DEFAULT_CSP_POLICY",
    # API response keys
    "API_OK_KEY",
    "API_DATA_KEY",
    "API_ERROR_KEY",
    "API_I18N_KEY",
]
