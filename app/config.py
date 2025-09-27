from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, List, Optional, Set, Tuple

from dotenv import load_dotenv


class ConfigError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.code = "ERR_INVALID_PAYLOAD"


ALERT_CHANNEL_ENUM: Set[str] = {"email", "sms", "kakao"}
INVENTORY_POLICY_ENUM: Set[str] = {"hold", "deduct_on_paid"}
LANG_ENUM: Set[str] = {"ko", "en"}


def _parse_bool(v: Optional[str], default: bool = False) -> bool:
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(v: Optional[str], default: int) -> int:
    if v is None or v == "":
        return default
    try:
        return int(v)
    except ValueError as e:
        raise ConfigError(f"Invalid integer value: {v}") from e


def _parse_csv(v: Optional[str]) -> List[str]:
    if not v:
        return []
    return [x.strip() for x in v.split(",") if x.strip()]


def _parse_set_lower_csv(v: Optional[str]) -> Set[str]:
    return {x.lower() for x in _parse_csv(v)}


def _require(key: str) -> str:
    val = os.getenv(key, "").strip()
    if not val:
        raise ConfigError(f"Missing required env: {key}")
    return val


def _optional(key: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip()


@dataclass(frozen=True)
class SMTPSettings:
    host: Optional[str]
    port: Optional[int]
    user: Optional[str]
    password: Optional[str]
    sender: Optional[str]


@dataclass(frozen=True)
class MapSettings:
    naver_client_id: Optional[str]
    naver_client_secret: Optional[str]


@dataclass(frozen=True)
class Settings:
    secret_key: str
    base_url: str
    default_lang: str
    timezone: str  # Display timezone (KST expected)
    storage_timezone: str  # Always 'UTC'
    mongo_url: str
    allowed_origins: Tuple[str, ...]
    smtp: SMTPSettings
    naver_map: MapSettings
    reminder_before_hours: int
    order_expire_hours: int
    inventory_policy: str
    upload_max_size_mb: int
    upload_allowed_exts: Tuple[str, ...]
    alert_channels: Tuple[str, ...]
    rate_limit_per_min: int
    csp_enable: bool

    def get_timezone(self) -> str:
        return self.timezone

    def get_allowed_origins(self) -> List[str]:
        return list(self.allowed_origins)


def _validate_lang(lang: str) -> str:
    if lang not in LANG_ENUM:
        raise ConfigError(f"DEFAULT_LANG must be one of {sorted(LANG_ENUM)}")
    return lang


def _validate_inventory_policy(policy: str) -> str:
    if policy not in INVENTORY_POLICY_ENUM:
        raise ConfigError(f"INVENTORY_POLICY must be one of {sorted(INVENTORY_POLICY_ENUM)}")
    return policy


def _validate_alert_channels(chs: Iterable[str]) -> Tuple[str, ...]:
    lower = [c.lower() for c in chs]
    invalid = [c for c in lower if c not in ALERT_CHANNEL_ENUM]
    if invalid:
        raise ConfigError(
            f"ALERT_CHANNELS contains invalid values {invalid}; allowed {sorted(ALERT_CHANNEL_ENUM)}"
        )
    # preserve original order, unique
    seen: Set[str] = set()
    ordered = []
    for c in lower:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return tuple(ordered)


def _validate_exts(exts: Iterable[str]) -> Tuple[str, ...]:
    cleaned = []
    for e in exts:
        e = e.lower().lstrip(".")
        if not e:
            continue
        cleaned.append(e)
    if not cleaned:
        raise ConfigError("UPLOAD_ALLOWED_EXTS must not be empty")
    # Unique while preserving order
    seen: Set[str] = set()
    ordered = []
    for e in cleaned:
        if e not in seen:
            seen.add(e)
            ordered.append(e)
    return tuple(ordered)


@lru_cache(maxsize=1)
def load_config() -> Settings:
    load_dotenv(override=False)

    secret_key = _require("SECRET_KEY")
    tz = _optional("TIMEZONE", "Asia/Seoul") or "Asia/Seoul"
    base_url = _optional("BASE_URL", "http://localhost") or "http://localhost"
    default_lang = _validate_lang(_optional("DEFAULT_LANG", "ko") or "ko")

    mongo_url = _require("MONGO_URL")

    allowed_origins_list = tuple(_parse_csv(_optional("ALLOWED_ORIGINS", "")))

    smtp = SMTPSettings(
        host=_optional("SMTP_HOST"),
        port=_parse_int(_optional("SMTP_PORT"), None) if _optional("SMTP_PORT") else None,
        user=_optional("SMTP_USER"),
        password=_optional("SMTP_PASS"),
        sender=_optional("SMTP_FROM"),
    )

    map_cfg = MapSettings(
        naver_client_id=_optional("NAVER_MAP_CLIENT_ID"),
        naver_client_secret=_optional("NAVER_MAP_CLIENT_SECRET"),
    )

    reminder_before_hours = _parse_int(_optional("REMINDER_BEFORE_HOURS"), 24)
    order_expire_hours = _parse_int(_optional("ORDER_EXPIRE_HOURS"), 48)
    inventory_policy = _validate_inventory_policy(_optional("INVENTORY_POLICY", "hold") or "hold")
    upload_max_size_mb = _parse_int(_optional("UPLOAD_MAX_SIZE_MB"), 10)
    upload_allowed_exts = _validate_exts(_parse_csv(_optional("UPLOAD_ALLOWED_EXTS", "jpg,jpeg,png,webp,pdf")))
    alert_channels = _validate_alert_channels(_parse_csv(_optional("ALERT_CHANNELS", "email,sms,kakao")))
    rate_limit_per_min = _parse_int(_optional("RATE_LIMIT_PER_MIN"), 60)
    csp_enable = _parse_bool(_optional("CSP_ENABLE"), True)

    return Settings(
        secret_key=secret_key,
        base_url=base_url,
        default_lang=default_lang,
        timezone=tz,
        storage_timezone="UTC",
        mongo_url=mongo_url,
        allowed_origins=allowed_origins_list,
        smtp=smtp,
        naver_map=map_cfg,
        reminder_before_hours=reminder_before_hours,
        order_expire_hours=order_expire_hours,
        inventory_policy=inventory_policy,
        upload_max_size_mb=upload_max_size_mb,
        upload_allowed_exts=upload_allowed_exts,
        alert_channels=alert_channels,
        rate_limit_per_min=rate_limit_per_min,
        csp_enable=csp_enable,
    )


def get_timezone() -> str:
    return load_config().get_timezone()


def get_allowed_origins() -> List[str]:
    return load_config().get_allowed_origins()
