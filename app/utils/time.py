from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.constants import TZ_NAME

UTC = timezone.utc
KST = ZoneInfo(TZ_NAME)  # Expect "Asia/Seoul"


# --- helpers ---
def _ensure_aware(dt: datetime) -> None:
    if not isinstance(dt, datetime):
        raise TypeError("expected datetime")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("naive datetime is not allowed")


def now_utc() -> datetime:
    return datetime.now(UTC)


def utc_to_kst(dt_utc: datetime) -> datetime:
    _ensure_aware(dt_utc)
    return dt_utc.astimezone(KST)


def kst_to_utc(dt_kst: datetime) -> datetime:
    _ensure_aware(dt_kst)
    return dt_kst.astimezone(UTC)


def parse_iso8601(s: str) -> datetime:
    """
    Parse an ISO8601 string and return tz-aware datetime in UTC.
    Accepts 'Z' or offset. Raises ValueError on invalid input.
    """
    if not isinstance(s, str) or not s:
        raise ValueError("invalid iso8601 string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    _ensure_aware(dt)
    return dt.astimezone(UTC)


def to_iso8601(dt: datetime) -> str:
    """
    Serialize a tz-aware datetime to ISO8601 with trailing 'Z' (UTC).
    """
    _ensure_aware(dt)
    dt_utc = dt.astimezone(UTC)
    return dt_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_kst_date(s: str) -> date:
    """
    Parse 'YYYY-MM-DD' to a date (interpreted in KST context).
    """
    try:
        y, m, d = map(int, s.split("-"))
        return date(y, m, d)
    except Exception as e:  # noqa: BLE001
        raise ValueError("invalid KST date format, expected YYYY-MM-DD") from e


def kst_day_range_to_utc(date_kst: date) -> tuple[datetime, datetime]:
    """
    Given a KST calendar date, return the [start_utc, end_utc) UTC interval
    that covers that local day.
    """
    if not isinstance(date_kst, date):
        raise TypeError("expected date")
    start_kst = datetime.combine(date_kst, time.min, tzinfo=KST)
    end_kst = start_kst + timedelta(days=1)
    return start_kst.astimezone(UTC), end_kst.astimezone(UTC)


def next_monday_00_kst(ref: datetime | None = None) -> datetime:
    """
    Return next week's Monday 00:00 in KST (strictly after the current week).
    If ref is None, use current UTC time.
    """
    if ref is None:
        ref = now_utc()
    _ensure_aware(ref)
    ref_kst = ref.astimezone(KST)
    wd = ref_kst.weekday()  # Mon=0..Sun=6
    days_until_next_mon = 7 - wd if wd != 0 else 7
    next_mon = (ref_kst.date() + timedelta(days=days_until_next_mon))
    return datetime.combine(next_mon, time.min, tzinfo=KST)


def floor_to_slot(dt_utc: datetime, slot_min: int) -> datetime:
    """
    Floor a UTC datetime to the nearest earlier slot boundary in minutes.
    """
    _ensure_aware(dt_utc)
    if slot_min <= 0:
        raise ValueError("slot_min must be positive")
    dt_utc = dt_utc.astimezone(UTC)
    minutes = (dt_utc.minute // slot_min) * slot_min
    return dt_utc.replace(minute=minutes, second=0, microsecond=0)
