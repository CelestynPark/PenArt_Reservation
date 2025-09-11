from __future__ import annotations

import os
from enum import Enum
from typing import Final, FrozenSet


# === Error codes (string literals used across API) ===
ERR_INVALID_PAYLOAD: Final[str] = "ERR_INVALID_PAYLOAD"
ERR_NOT_FOUND: Final[str] = "ERR_NOT_FOUND"
ERR_UNAUTHORIZED: Final[str] = "ERR_UNAUTHORIZED"
ERR_FORBIDDEN: Final[str] = "ERR_FORBIDDEN"
ERR_CONFLICT: Final[str] = "ERR_CONFLICT"
ERR_POLICY_CUTOFF: Final[str] = "ERR_POLICY_CUTOFF"
ERR_RATE_LIMIT: Final[str] = "ERR_RATE_LIMIT"
ERR_SLOT_BLOCKED: Final[str] = "ERR_SLOT_BLOCKED"
ERR_INTERNAL: Final[str] = "ERR_INTERNAL"

ERROR_CODES: Final[FrozenSet[str]] = frozenset(
    {
        ERR_INVALID_PAYLOAD,
        ERR_NOT_FOUND,
        ERR_UNAUTHORIZED,
        ERR_FORBIDDEN,
        ERR_CONFLICT,
        ERR_POLICY_CUTOFF,
        ERR_RATE_LIMIT,
        ERR_SLOT_BLOCKED,
        ERR_INTERNAL,
    }
)


# === Enums (string values must match API schema) ===
class BookingStatus(str, Enum):
    requested = "requested"
    confirmed = "confirmed"
    completed = "completed"
    canceled = "canceled"
    no_show = "no_show"


class OrderStatus(str, Enum):
    created = "created"
    awaiting_deposit = "awaiting_deposit"
    paid = "paid"
    canceled = "canceled"
    expired = "expired"


class ReviewStatus(str, Enum):
    published = "published"
    hidden = "hidden"
    flagged = "flagged"


class GoodsStatus(str, Enum):
    draft = "draft"
    published = "published"


class Channel(str, Enum):
    email = "email"
    sms = "sms"
    kakao = "kakao"


class Source(str, Enum):
    web = "web"
    admin = "admin"
    kakao = "kakao"


# === Codes / Slugging ===
BOOKING_PREFIX: Final[str] = "BKG"
ORDER_PREFIX: Final[str] = "ORD"
CODE_BASE36_LEN: Final[int] = 6  # e.g., ABC123 (base-36, uppercase or lowercase handled by generator)


# === Pagination defaults ===
PAGE_DEFAULT: Final[int] = 1
SIZE_DEFAULT: Final[int] = 20
SIZE_MAX: Final[int] = 100


# === Timezone / Language (display vs storage: storage is UTC; display KST) ===
TZ_NAME: Final[str] = os.getenv("TIMEZONE", "Asia/Seoul")
DEFAULT_LANG: Final[str] = os.getenv("DEFAULT_LANG", "ko")


# === Upload policy ===
def _parse_allowed_exts(env_val: str | None) -> FrozenSet[str]:
    raw = env_val or "jpg,jpeg,png,webp,pdf"
    # Store lowercased extensions without leading dot, e.g., {"jpg","png"}
    items = (e.strip().lower().lstrip(".") for e in raw.split(","))
    return frozenset(filter(None, items))


UPLOAD_ALLOWED_EXTS: Final[FrozenSet[str]] = _parse_allowed_exts(os.getenv("UPLOAD_ALLOWED_EXTS"))
try:
    UPLOAD_MAX_SIZE_MB: Final[int] = int(os.getenv("UPLOAD_MAX_SIZE_MB", "10"))
except ValueError:
    UPLOAD_MAX_SIZE_MB = 10  # safe fallback


# === Rate limit (global default per minute) ===
try:
    RATE_LIMIT_PER_MIN: Final[int] = int(os.getenv("RATE_LIMIT_PER_MIN", "60"))
except ValueError:
    RATE_LIMIT_PER_MIN = 60


# === CSP toggle ===
CSP_ENABLE: Final[bool] = (os.getenv("CSP_ENABLE", "true").lower() == "true")


__all__ = [
    # errors
    "ERR_INVALID_PAYLOAD",
    "ERR_NOT_FOUND",
    "ERR_UNAUTHORIZED",
    "ERR_FORBIDDEN",
    "ERR_CONFLICT",
    "ERR_POLICY_CUTOFF",
    "ERR_RATE_LIMIT",
    "ERR_SLOT_BLOCKED",
    "ERR_INTERNAL",
    "ERROR_CODES",
    # enums
    "BookingStatus",
    "OrderStatus",
    "ReviewStatus",
    "GoodsStatus",
    "Channel",
    "Source",
    # codes
    "BOOKING_PREFIX",
    "ORDER_PREFIX",
    "CODE_BASE36_LEN",
    # pagination
    "PAGE_DEFAULT",
    "SIZE_DEFAULT",
    "SIZE_MAX",
    # tz/lang
    "TZ_NAME",
    "DEFAULT_LANG",
    # uploads
    "UPLOAD_ALLOWED_EXTS",
    "UPLOAD_MAX_SIZE_MB",
    # rate limit / csp
    "RATE_LIMIT_PER_MIN",
    "CSP_ENABLE",
]