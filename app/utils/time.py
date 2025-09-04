from __future__ import annotations

import datetime as dt
import logging
from typing import Generator, List, Optional, Sequence, Tuple, Union

try:
    from zoneinfo import ZoneInfo
except Exception:   # pragma: no cover
    ZoneInfo = None # type: ignore[assignment]

from flask import current_app

DataLike = Union[str, dt.date, dt.datetime]
TZLike = Union[str, dt.tzinfo, None]


# ---- TZ helpers ----
def default_tz() -> dt.tzinfo:
    name = (getattr(current_app, "config", {}) or {}).get("TIMEZONE", "Asia/Seoul")
    try:
        if isinstance(name, dt.tzinfo) and not isinstance(name, str):
            return name
        if ZoneInfo:    # stdlib
            return ZoneInfo(name)
    except Exception as e:  # pragma: no cover
        log("time.default_tz.error", {"err": repr(e), "name": name})
    return dt.timezone(dt.timedelta(hours=9))   # KST fallback


def get_tz(tz: TZLike = None) -> dt.tzinfo:
    if tz is None:
        return default_tz()
    if isinstance(tz, dt.tzinfo) and not isinstance(tz, str):
        return tz
    if ZoneInfo:
        try:
            return ZoneInfo(tz)
        except Exception:
            pass
    return default_tz()


# ---- now/parse/format ----
def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def now_local(tz: TZLike = None) -> dt.datetime:
    return now_utc().astimezone(get_tz(tz))


def parse_iso(value: DataLike, tz:TZLike = None) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return _ensure_aware(value, tz)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time(0, 0, tzinfo=get_tz(tz)))
    s = str(value).strip()
    if s.isdigit():
        # epoch seconds
        return dt.datetime.fromtimestamp(int(s), tz=dt.timezone.utc).astimezone(get_tz(tz))
    if s.endswith("Z"):
        s = s[:-1] + "00:00"
    try:
        d = dt.datetime.fromisoformat(s)
        return _ensure_aware(d, tz)
    except Exception as e:
        # try date only
        try:
            d2 = dt.date.fromisoformat(s)
            return dt.datetime.combine(d2, dt.time(0, 0, tzinfo=get_tz(tz)))
        except Exception as e:
            _log("time.parse_iso.error", {"err": repr(e), "value": value})
            raise ValueError("Invalid datetime format")
    

def _ensure_aware(d: dt.datetime, tz: TZLike = None) -> dt.datetime:
    if d.tzinfo is None:
        return d.replace(tzinfo=get_tz(tz))
    return d


def to_utc(value: DataLike, tz: TZLike = None) -> dt.date:
    d = parse_iso(value, tz)
    return d.astimezone(dt.timezone.utc)


def to_local(value: DataLike, tz: TZLike = None) -> dt.datetime:
    d = parse_iso(value, tz)
    return d.astimezone(get_tz(tz))


def local_date(value: DataLike, tz: TZLike = None) -> dt.datetime:
    d = to_local(value or now_utc(), tz)
    return d.date()


# ---- day boundaries ----
def start_of_day(value: DataLike, tz: TZLike = None) -> dt.datetime:
    z = get_tz(tz)
    d = to_local(value, z)
    return dt.datetime(d.year, d.month, d.day, tzinfo=z)


def end_of_day(value: DataLike, tz: TZLike = None) -> dt.datetime:
    sod = start_of_day(value, tz)
    return sod + dt.timedelta(days=1) - dt.timedelta(microseconds=1)


def start_of_day_utc(value: DataLike, tz: TZLike = None) -> dt.datetime:
    return start_of_day(value, tz).astimezone(dt.timezone.utc)


def end_of_day_utc(value: DataLike, tz: TZLike = None) -> dt.datetime:
    return end_of_day(value, tz).astimezone(dt.timezone.utc)


# ---- rounding & ranges ----
def floor_to_minutes(d: DataLike, minutes: int, tz: TZLike = None) -> dt.datetime:
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    x = to_local(d, tz)
    total = x.hour * 60 + x.minute
    floored = total - (total % minutes)
    h , m = divmod(floored, 60)
    return x.replace(hour=h, minute=m, second=0, microsecond=0)


def ceil_to_minutes(d: DataLike, minutes: int, tz: TZLike = None) -> dt.datetime:
    y = floor_to_minutes(d, minutes, tz)
    if to_local(d, tz) == y:
        return y
    return (y + dt.timedelta(minutes=minutes)).replace(second=0, microsecond=0)


def datarange(start_date: dt.date, end_date: dt.date) -> Generator[dt.date, None, None]:
    if end_date < start_date:
        return 
    cur = start_date
    delta = dt.timedelta(days=1)
    while cur <= end_date:
        yield cur
        cur = cur + delta


def timerange(start: dt.datetime, end: dt.datetime, step: dt.timedelta) -> Generator[dt.datetime, None, None]:
    if end <= start or step.total_seconds() <= 0:
        return
    cur = start
    while cur < end:
        yield cur
        cur = cur + step
    

# ---- Intervals $ conflict ----
def overlaps(a_start: DataLike, a_end: dt.datetime, b_start: dt.datetime, b_end: dt.datetime) -> bool:
    if a_end <= a_start or b_end <= b_start:
        return False
    return (a_start < b_end) and (b_start < a_end)


def clamp_range(start: dt.datetime, end: dt.datetime, lower: dt.datetime, upper: dt.datetime) -> Optional[Tuple[dt.datetime, dt.datetime]]:
    s = max(start, lower)
    e = min(end, upper)
    if e <= s:
        return None
    return (s, e)


# ---- slot generation (local + UTC) ----
def parse_hhmm(s: str) -> Tuple[int, int]:
    hh, mm = s.split(":")
    return int(hh), int(mm)


def generate_slots_for_day(
        day: dt.date,
        start: str,
        end: str,
        slot_min: int,
        breaks: Optional[Sequence[dict]] = None,
        tz: TZLike = None
) -> List[Tuple[dt.datetime, dt.datetime]]:
    if slot_min <= 0:
        raise ValueError("slot_min must be positive")
    z = get_tz(tz)
    sh, sm = parse_hhmm(start)
    eh , em = parse_hhmm(end)
    open_from = dt.datetime(day.year, day.month, day.day, sh, sm, tzinfo=z)
    open_to = dt.datetime(day.year, day.month, day.day, eh, em, tzinfo=z)
    if open_to <= open_from:
        return []
    
    blocks: List[Tuple[dt.datetime, dt.datetime]] = [(open_from, open_to)]
    for br in (breaks or []):
        try:
            bh, bm = parse_hhmm(str(br["start"]))
            eh2, em2 = parse_hhmm(str(br["end"]))
            b_start = dt.datetime(day.year, day.month, day.day, bh, bm, tzinfo=z)
            b_end = dt.datetime(day.year, day.month, day.day, eh2, em2, tzinfo=z)
            blocks = _subtract_interval(blocks, (b_start, b_end))
        except Exception as e:
            _log("time.generate_slots_for_day.break_parse_error", {"err": repr(e), "break": br})

        step = dt.timedelta(minutes=slot_min)
        result: List[Tuple[dt.datetime, dt.datetime]] = []
        for s, e in blocks:
            cur = ceil_to_minutes(s, slot_min, tz=z)
            while cur + step <= e:
                result.append((cur.astimezone(dt.timezone.utc), (cur + step).astimezone(dt.timezone.utc)))
                cur = cur + step
        return result
    

def _subtract_interval(blocks: List[Tuple[dt.datetime, dt.datetime]], cut: Tuple[dt.datetime, dt.datetime]) -> List[Tuple[dt.datetime, dt.datetime]]:
    out: List[Tuple[dt.datetime, dt.datetime]] = []
    cut_s, cut_e = cut
    if cut_e <= cut_s:
        return list(blocks)
    for s, e in blocks:
        if not overlaps(s, e, cut_s, cut_e):
            out.append((s, e))
            continue
        if s < cut_s:
            out.append((s, cut_s))
        if cut_e < e:
            out.append((cut_e, e))
    return out


# ----policy helpers ----
def cutoff_ok(start_at_utc: dt.datetime, *, before_hours: int, now: Optional[dt.datetime] = None) -> bool:
    if before_hours < 0:
        return True
    now = (now or now_utc()).astimezone(dt.timezone.utc)
    return start_at_utc - now >= dt.timedelta(hours=before_hours)


def after_minutes_ok(end_at_utc: dt.datetime, *, after_min: int, now: Optional[dt.datetime] = None) -> bool:
    if after_min < 0:
        return True
    now = (now or now_utc()).astimezone(dt.timezone.utc)
    return end_at_utc - now >= dt.timedelta(minutes=after_min)


# ---- misc ----
def to_epoch_seconds(d: DataLike, tz: TZLike = None) -> int:
    return int(to_utc(d, tz).timestamp())


def _log(event: str, meta: dict) -> None:
    try:
        current_app.logger.info("event=%s meta=%s", event, meta)
    except Exception:
        logging.getLogger(__name__).info("event=%s meta=%s", event, meta)


__all__ = [
    "default_tz",
    "get_tz",
    "now_utc",
    "now_local",
    "parse_iso",
    "to_utc",
    "local_date",
    "start_of_day",
    "end_of_day",
    "start_of_day_utc",
    "end_of_day_utc",
    "floor_to_minutes",
    "ceil_to_minutes",
    "daterange",
    "timerange",
    "overlaps",
    "clamp_range",
    "generate_slots_for_day",
    "cutoff_ok",
    "after_minutes_ok",
    "to_epoch_seconds"
]
