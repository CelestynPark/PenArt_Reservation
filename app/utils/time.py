from __future__ import annotations

from datetime import datetime, timezone, timedelta
from functools import lru_cache
from typing import Tuple, Union

import pytz
from dateutil import parser as date_parser

from app.config import load_config

__all__ = [
    "now_utc",
    "to_utc",
    "to_kst",
    "parse_kst_date",
    "isoformat_utc",
]

DateInput = Union[datetime, str]


@lru_cache(maxsize=1)
def _tz_kst() -> pytz.BaseTzInfo:
    tz_name = load_config().timezone or "Asia/Seoul"
    return pytz.timezone(tz_name)


def _coerce_datetime(value: DateInput) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date_parser.isoparse(value)
        except Exception as e:
            raise ValueError(f"invalid datetime string: {value}") from e
    raise ValueError("unsupported datetime input")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(dt_or_str: DateInput) -> datetime:
    dt = _coerce_datetime(dt_or_str)
    if dt.tzinfo is None:
        # naive → assume UTC (server-storage default)
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_kst(dt_or_str: DateInput) -> datetime:
    dt = _coerce_datetime(dt_or_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz_kst())


def parse_kst_date(date_str: str) -> Tuple[datetime, datetime]:
    # Input: 'YYYY-MM-DD' (interpreted in KST local calendar day)
    if not isinstance(date_str, str) or len(date_str) != 10:
        raise ValueError("date_str must be 'YYYY-MM-DD'")
    try:
        y, m, d = [int(x) for x in date_str.split("-")]
    except Exception as e:
        raise ValueError("date_str must be 'YYYY-MM-DD'") from e

    kst = _tz_kst()
    start_kst = kst.localize(datetime(y, m, d, 0, 0, 0))
    end_kst = start_kst + timedelta(days=1)

    start_utc = start_kst.astimezone(timezone.utc)
    end_utc = end_kst.astimezone(timezone.utc)
    return start_utc, end_utc


def isoformat_utc(dt_or_str: DateInput) -> str:
    dt_utc = to_utc(dt_or_str)
    # Use seconds precision; ensure 'Z' suffix
    return dt_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z")
