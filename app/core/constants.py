from __future__ import annotations

from enum import StrEnum

# --- Languages ---
LANG_KO = "ko"
LANG_EN = "en"
SUPPORTED_LANGS = (LANG_KO, LANG_EN)

# --- Timezone (display) ---
KST_TZ = "Asia/Seoul"

# --- Pagination ---
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# --- Code / Slug conventions ---
CODE_PREFIX_BOOKING = "BKG"
CODE_PREFIX_ORDER = "ORD"
CODE_RANDOM_BASE = 36
CODE_RANDOM_LEN = 6  # e.g., BASE36(6)

# --- Error codes (response.error.code) ---
class ErrorCode(StrEnum):
    INVALID_PAYLOAD = "ERR_INVALID_PAYLOAD"
    NOT_FOUND = "ERR_NOT_FOUND"
    UNAUTHORIZED = "ERR_UNAUTHORIZED"
    FORBIDDEN = "ERR_FORBIDDEN"
    CONFLICT = "ERR_CONFLICT"
    POLICY_CUTOFF = "ERR_POLICY_CUTOFF"
    RATE_LIMIT = "ERR_RATE_LIMIT"
    SLOT_BLOCKED = "ERR_SLOT_BLOCKED"
    INTERNAL = "ERR_INTERNAL"


# --- Enums (must match API schema one-to-one) ---
class BookingStatus(StrEnum):
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    COMPLETED = "completed"
    CANCELED = "canceled"
    NO_SHOW = "no_show"


class OrderStatus(StrEnum):
    CREATED = "created"
    AWAITING_DEPOSIT = "awaiting_deposit"
    PAID = "paid"
    CANCELED = "canceled"
    EXPIRED = "expired"


class GoodsStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class ReviewStatus(StrEnum):
    PUBLISHED = "published"
    HIDDEN = "hidden"
    FLAGGED = "flagged"


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    KAKAO = "kakao"


class Source(StrEnum):
    WEB = "web"
    ADMIN = "admin"
    KAKAO = "kakao"


class UserRole(StrEnum):
    CUSTOMER = "customer"
    ADMIN = "admin"
