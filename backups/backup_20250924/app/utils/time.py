from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Tuple, Union
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.core.constants import KST_TZ

__all__ = (
    "to_utc",
    "to_kst",
    "parse_kst_date",
    "range_utc",
    "iso",
)

# Cache timezones
_SETTINGS = get_settings()
LOCAL_TZ = ZoneInfo(_SETTINGS.TIMEZONE or KST_TZ)
UTC = timezone.utc


def _is_date_str(s: str) -> bool:
    return len(s) == 10 and s[4] == "-" and s[7] == "-"


def _parse_iso_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        raise ValueError("Invalid datetime string")
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _ensure_aware(dt: datetime, assume_tz: timezone | ZoneInfo) -> datetime:
    return dt.replace(tzinfo=assume_tz) if dt.tzinfo is None else dt


def to_utc(value: Union[datetime, str, date]) -> datetime:
    """
    Interpret input as KST/local time and convert to UTC.
    - datetime naive => assume LOCAL_TZ
    - ISO8601 string with tz => respected; without tz => assume LOCAL_TZ
    - 'YYYY-MM-DD' => that day's 00:00:00 at LOCAL_TZ
    - date => 00:00:00 at LOCAL_TZ
    """
    if isinstance(value, date) and not isinstance(value, datetime):
        dt_local = datetime.combine(value, time.min, tzinfo=LOCAL_TZ)
        return dt_local.astimezone(UTC)

    if isinstance(value, str):
        if _is_date_str(value):
            d = parse_kst_date(value)
            dt_local = datetime.combine(d, time.min, tzinfo=LOCAL_TZ)
            return dt_local.astimezone(UTC)
        dt = _parse_iso_dt(value)
        # If parsed as naive (assumed UTC in _parse_iso_dt), but we need "KST semantics" for to_utc
        if dt.tzinfo is UTC and ("T" in value and not any(ch in value for ch in "+-Z")):
            dt = dt.replace(tzinfo=LOCAL_TZ)
        return dt.astimezone(UTC)

    if isinstance(value, datetime):
        dt_local = _ensure_aware(value, LOCAL_TZ)
        # If input had explicit non-local tz, treat as given and convert
        if dt_local.tzinfo is None:
            dt_local = dt_local.replace(tzinfo=LOCAL_TZ)
        return dt_local.astimezone(UTC)

    raise ValueError("Unsupported type for to_utc")


def to_kst(value: Union[datetime, str]) -> datetime:
    """
    Interpret input as UTC and convert to LOCAL_TZ.
    - datetime naive => assume UTC
    - ISO8601 string with tz => respected; without tz => assume UTC
    """
    if isinstance(value, str):
        dt = _parse_iso_dt(value)  # naive -> assumed UTC
        return dt.astimezone(LOCAL_TZ)

    if isinstance(value, datetime):
        dt_utc = _ensure_aware(value, UTC)
        return dt_utc.astimezone(LOCAL_TZ)

    raise ValueError("Unsupported type for to_kst")


def parse_kst_date(s: str) -> date:
    if not _is_date_str(s):
        raise ValueError("Invalid date string, expected YYYY-MM-DD")
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception:
        raise ValueError("Invalid date string")


def range_utc(start_kst: Union[date, str], end_kst: Union[date, str]) -> Tuple[datetime, datetime]:
    """
    Return UTC range [start, end) for KST-local calendar dates.
    End is exclusive: from 00:00:00 of start_kst to 00:00:00 of (end_kst + 1 day) in LOCAL_TZ.
    """
    if isinstance(start_kst, str):
        start_kst = parse_kst_date(start_kst)
    if isinstance(end_kst, str):
        end_kst = parse_kst_date(end_kst)

    start_local = datetime.combine(start_kst, time.min, tzinfo=LOCAL_TZ)
    end_local = datetime.combine(end_kst + timedelta(days=1), time.min, tzinfo=LOCAL_TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def iso(dt_utc: datetime) -> str:
    """
    Serialize UTC datetime to ISO8601 with 'Z' suffix.
    """
    if not isinstance(dt_utc, datetime):
        raise ValueError("iso() expects datetime")
    dt_utc = _ensure_aware(dt_utc, UTC).astimezone(UTC).replace(microsecond=0)
    return dt_utc.isoformat().replace("+00:00", "Z")
