from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence
from zoneinfo import ZoneInfo

from app.core.constants import SUPPORTED_LANGS, KST_TZ, LANG_KO


def _getenv(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key)
    if v is None or v == "":
        return default
    return v


def _getenv_int(key: str, default: int) -> int:
    v = _getenv(key)
    try:
        return int(v) if v is not None else default
    except Exception:
        return default


def _getenv_bool(key: str, default: bool) -> bool:
    v = (_getenv(key) or "").strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off"):
        return False
    return default


def _getenv_csv(key: str, default: Sequence[str] | None = None) -> List[str]:
    v = _getenv(key)
    if not v:
        return list(default or [])
    return [x.strip() for x in v.split(",") if x.strip()]


def _validate_timezone(tz: str) -> str:
    try:
        ZoneInfo(tz)
        return tz
    except Exception:
        return KST_TZ


def _one_of(value: str, allowed: Sequence[str], fallback: str) -> str:
    return value if value in allowed else fallback


@dataclass(slots=True)
class Settings:
    # Required
    MONGO_URL: str
    SECRET_KEY: str

    # App
    TIMEZONE: str = field(default=KST_TZ)  # display KST, internal UTC
    BASE_URL: Optional[str] = field(default=None)
    DEFAULT_LANG: str = field(default=LANG_KO)
    ALLOWED_ORIGINS: List[str] = field(default_factory=list)

    # Mail
    SMTP_HOST: Optional[str] = field(default=None)
    SMTP_PORT: Optional[int] = field(default=None)
    SMTP_USER: Optional[str] = field(default=None)
    SMTP_PASS: Optional[str] = field(default=None)
    SMTP_FROM: Optional[str] = field(default=None)

    # Naver Map
    NAVER_MAP_CLIENT_ID: Optional[str] = field(default=None)
    NAVER_MAP_CLIENT_SECRET: Optional[str] = field(default=None)

    # Business Policies (defaults fixed by spec)
    REMINDER_BEFORE_HOURS: int = field(default=24)
    ORDER_EXPIRE_HOURS: int = field(default=48)
    INVENTORY_POLICY: str = field(default="hold")  # hold|deduct_on_paid

    # Uploads
    UPLOAD_MAX_SIZE_MB: int = field(default=10)
    UPLOAD_ALLOWED_EXTS: List[str] = field(default_factory=lambda: ["jpg", "jpeg", "png", "webp", "pdf"])

    # Alerts / Limits / CSP
    ALERT_CHANNELS: List[str] = field(default_factory=lambda: ["email", "sms", "kakao"])
    RATE_LIMIT_PER_MIN: int = field(default=60)
    CSP_ENABLE: bool = field(default=True)

    # Runtime mode helpers
    ENV: str = field(default_factory=lambda: _getenv("ENV", _getenv("FLASK_ENV", "production")) or "production")
    DEBUG: bool = field(default_factory=lambda: _getenv_bool("DEBUG", False))
    TESTING: bool = field(default_factory=lambda: _getenv_bool("TESTING", False))

    def as_dict(self) -> dict:
        return {
            "MONGO_URL": self.MONGO_URL,
            "SECRET_KEY": "***" if self.SECRET_KEY else "",
            "TIMEZONE": self.TIMEZONE,
            "BASE_URL": self.BASE_URL,
            "DEFAULT_LANG": self.DEFAULT_LANG,
            "ALLOWED_ORIGINS": self.ALLOWED_ORIGINS,
            "SMTP_HOST": self.SMTP_HOST,
            "SMTP_PORT": self.SMTP_PORT,
            "SMTP_FROM": self.SMTP_FROM,
            "NAVER_MAP_CLIENT_ID": self.NAVER_MAP_CLIENT_ID,
            "REMINDER_BEFORE_HOURS": self.REMINDER_BEFORE_HOURS,
            "ORDER_EXPIRE_HOURS": self.ORDER_EXPIRE_HOURS,
            "INVENTORY_POLICY": self.INVENTORY_POLICY,
            "UPLOAD_MAX_SIZE_MB": self.UPLOAD_MAX_SIZE_MB,
            "UPLOAD_ALLOWED_EXTS": self.UPLOAD_ALLOWED_EXTS,
            "ALERT_CHANNELS": self.ALERT_CHANNELS,
            "RATE_LIMIT_PER_MIN": self.RATE_LIMIT_PER_MIN,
            "CSP_ENABLE": self.CSP_ENABLE,
            "ENV": self.ENV,
            "DEBUG": self.DEBUG,
            "TESTING": self.TESTING,
        }

    @property
    def is_production(self) -> bool:
        return (self.ENV or "").lower() == "production"

    @property
    def is_development(self) -> bool:
        return (self.ENV or "").lower() in ("development", "dev")

    @property
    def is_testing(self) -> bool:
        return self.TESTING


_SETTINGS: Optional[Settings] = None


def _build_settings() -> Settings:
    mongo_url = _getenv("MONGO_URL")
    secret_key = _getenv("SECRET_KEY")

    if not mongo_url:
        raise RuntimeError("Missing required environment variable: MONGO_URL")
    if not secret_key:
        raise RuntimeError("Missing required environment variable: SECRET_KEY")

    timezone = _validate_timezone(_getenv("TIMEZONE", KST_TZ) or KST_TZ)
    base_url = _getenv("BASE_URL")

    default_lang = _one_of((_getenv("DEFAULT_LANG", LANG_KO) or LANG_KO), SUPPORTED_LANGS, LANG_KO)
    allowed_origins = _getenv_csv("ALLOWED_ORIGINS", [])

    smtp_host = _getenv("SMTP_HOST")
    smtp_port = _getenv_int("SMTP_PORT", int(_getenv("SMTP_PORT") or 0)) if _getenv("SMTP_PORT") else None
    smtp_user = _getenv("SMTP_USER")
    smtp_pass = _getenv("SMTP_PASS")
    smtp_from = _getenv("SMTP_FROM")

    naver_id = _getenv("NAVER_MAP_CLIENT_ID")
    naver_secret = _getenv("NAVER_MAP_CLIENT_SECRET")

    reminder_before_hours = _getenv_int("REMINDER_BEFORE_HOURS", 24)
    order_expire_hours = _getenv_int("ORDER_EXPIRE_HOURS", 48)
    inventory_policy = _one_of((_getenv("INVENTORY_POLICY", "hold") or "hold"), ("hold", "deduct_on_paid"), "hold")

    upload_max_size_mb = _getenv_int("UPLOAD_MAX_SIZE_MB", 10)
    upload_allowed_exts = [e.lower() for e in _getenv_csv("UPLOAD_ALLOWED_EXTS", ["jpg", "jpeg", "png", "webp", "pdf"])]

    alert_channels = [c for c in _getenv_csv("ALERT_CHANNELS", ["email", "sms", "kakao"]) if c in ("email", "sms", "kakao")]
    if not alert_channels:
        alert_channels = ["email", "sms", "kakao"]

    rate_limit_per_min = _getenv_int("RATE_LIMIT_PER_MIN", 60)
    csp_enable = _getenv_bool("CSP_ENABLE", True)

    env = _getenv("ENV", _getenv("FLASK_ENV", "production")) or "production"
    debug = _getenv_bool("DEBUG", False)
    testing = _getenv_bool("TESTING", False)

    return Settings(
        MONGO_URL=mongo_url,
        SECRET_KEY=secret_key,
        TIMEZONE=timezone,
        BASE_URL=base_url,
        DEFAULT_LANG=default_lang,
        ALLOWED_ORIGINS=allowed_origins,
        SMTP_HOST=smtp_host,
        SMTP_PORT=smtp_port,
        SMTP_USER=smtp_user,
        SMTP_PASS=smtp_pass,
        SMTP_FROM=smtp_from,
        NAVER_MAP_CLIENT_ID=naver_id,
        NAVER_MAP_CLIENT_SECRET=naver_secret,
        REMINDER_BEFORE_HOURS=reminder_before_hours,
        ORDER_EXPIRE_HOURS=order_expire_hours,
        INVENTORY_POLICY=inventory_policy,
        UPLOAD_MAX_SIZE_MB=upload_max_size_mb,
        UPLOAD_ALLOWED_EXTS=upload_allowed_exts,
        ALERT_CHANNELS=alert_channels,
        RATE_LIMIT_PER_MIN=rate_limit_per_min,
        CSP_ENABLE=csp_enable,
        ENV=env,
        DEBUG=debug,
        TESTING=testing,
    )


def get_settings(refresh: bool = False) -> Settings:
    global _SETTINGS
    if _SETTINGS is None or refresh:
        _SETTINGS = _build_settings()
    return _SETTINGS
