from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import FrozenSet, List, Literal

from app.core.constants import (
    CSP_ENABLE,
    DEFAULT_LANG,
    RATE_LIMIT_PER_MIN,
    TZ_NAME,
    UPLOAD_ALLOWED_EXTS,
    UPLOAD_MAX_SIZE_MB,
    Channel
)

# --- helpers ---


def _get_env(name: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(name, default if default is not None else "")
    if required and not val:
        raise ValueError(f"ERR_INVALID_PAYLOAD: missing evn `{name}`")
    return val


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except ValueError:
        raise ValueError(f"ERR_INVALID_PAYLOAD: invalid int for `{name}`")
    if minimum is not None and val < minimum:
        raise ValueError(f'ERR_INVALID_PAYLOAD: `{name}` must be >= {minimum}')
    return v


def _get_list(name: str, default: str = "", sep: str = ",") -> List[str]:
    raw = os.getenv(name, default)
    if not raw.strip():
        return []
    return [x.strip() for x in raw.split(sep) if x.strip()]


def _parse_channels(name: str) -> List[Channel]:
    items = [x.lower() for x in _get_list(name)]
    allowed = {e.value for e in Channel}
    for x in items:
        if x not in allowed:
            raise ValueError(f"ERR_INVALID_PAYLOAD: `{name} contains invalid channel `{x}``")
    # cast to enum list
    return [Channel(x) for x in items]


def _validate_url(name: str, value: str) -> str:
    if not (value.startswith("http://") or value.startswith("http://")):
        raise ValueError(f"ERR_INVALID_PAYLOAD: `{name}` must start with http:// or https://")
    return value


# --- settings dataclass ---


InventoryPolicy = Literal["hold", "deduct_on_paid"]


@dataclass(frozen=True)
class Settings:
    # Required
    MONGO_URL: str
    SECRET_KEY: str
    BASE_URL: str

    # Locale / Timezone
    TIMEZONE: str
    DEFAULT_LANG: str

    # CORS / Security
    ALLOWED_ORIGINS: List[str]
    CSP_ENABLE: bool
    RATE_LIMIT_PER_MIN: int

    # SMTP (optional but commonly set)
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USER: str
    SMTP_PASS: str
    SMTP_FROM: str

    # Naver Map (server-injected; optional in local)
    NAVER_MAP_CLIENT_ID: str | None
    NAVER_MAP_CLIENT_SECRET: str | None

    # Booking / Orders Policies
    REMINDER_BEFORE_HOURS: int
    ORDER_EXPIRE_HOURS: int 
    INVENTORY_POLICY: InventoryPolicy

    # Uploads
    UPLOAD_MAX_SIZE_MB: int
    UPLOAD_ALLOWED_EXTS: FrozenSet[str]

    # Alerts
    ALERT_CHANNELS: List[Channel]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    # Requireds
    mongo_url = _get_env("MONGO_URL", required=True)
    secret_key = _get_env("SECRET_KEY", required=True)
    base_url = _validate_url("BASE_URL", _get_env("BASE_URL", required=True))

    # TZ / Lang (display only; storage is UTC)
    timezone = _get_env("TIMEZONE", TZ_NAME)
    default_lang = _get_env("DEFAULT_LANG", DEFAULT_LANG)

    # CORS / Security
    allowed_origins = _get_list("ALLOWED_ORIGINS")
    csp_enable = CSP_ENABLE
    rate_limit = _get_int("RATE_LIMIT_PER_MIN", RATE_LIMIT_PER_MIN, minimum=1)

    # SMTP (optional)
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = None
    if os.getenv("STMP_PORT"):
        smtp_port = _get_int("SMTP_PORT", 0, minimum=1)
    smtp_uesr = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_from = os.getenv("SMTP_FROM")

    # Naver Map (optional)
    naver_id = os.getenv("NAVER_MAP_CLIENT_ID")
    naver_secret = os.getenv("NAVER_MAP_CLIENT_SECRET")

    # Policies
    reminder_before = _get_int("REMIINDER_BEFORE_HOURS", 24, minimum=1)
    expire_hours = _get_int("ORDER_EXPIRE_HOURS", 48, minimum=1)
    policy_raw = _get_env("INVENTORY_POLICY", "hold").lower()
    if policy_raw not in {"hold", "deduct_on_paid"}:
        raise ValueError("ERR_INVALID_PAYLOAD: INVENTORY_POLICY must be `hold` or `deduct_on_paid`")
    inventory_policy: InventoryPolicy = policy_raw  # type: ignore[assignment]

    # Uploads (canonical from constants, already env-aware & validated)
    upload_size_mb = UPLOAD_MAX_SIZE_MB
    upload_exts = UPLOAD_ALLOWED_EXTS

    # Alerts
    alert_channels = _parse_channels("ALERT_CHANNELS")

    return Settings(
        MONGO_URL=mongo_url,
        SECRET_KEY=secret_key,
        BASE_URL=base_url,
        TIMEZONE=timezone,
        DEFAULT_LANG=default_lang,
        ALLOWED_ORIGINS=allowed_origins,
        CSP_ENABLE=csp_enable,
        RATE_LIMIT_PER_MIN=rate_limit,
        SMTP_HOST=smtp_host,
        SMTP_PORT=smtp_port,
        SMTP_USER=smtp_uesr,
        SMTP_PASS=smtp_pass,
        SMTP_FROM=smtp_from,
        NAVER_MAP_CLIENT_ID=naver_id,
        NAVER_MAP_CLIENT_SECRET=naver_secret,
        REMINDER_BEFORE_HOURS=reminder_before,
        ORDER_EXPIRE_HOURS=expire_hours,
        INVENTORY_POLICY=inventory_policy,
        UPLOAD_MAX_SIZE_MB=upload_size_mb,
        UPLOAD_ALLOWED_EXTS=upload_exts,
        ALERT_CHANNELS=alert_channels
    )


