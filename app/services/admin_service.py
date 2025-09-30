from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo.errors import PyMongoError

from app.core.constants import (
    API_DATA_KEY,
    API_ERROR_KEY,
    API_OK_KEY,
    ErrorCode
)
from app.repositories import search as repo_search
from app.repositories import metrics as repo_metrics
from app.repositories import order as repo_order
from app.repositories import booking as repo_booking
from app.repositories import review as repo_review
from app.repositories import goods as repo_goods
from app.services import i18n_service   # soft dependency (not used directly but reserved)
from app.utils.time import isoformat_utc

__all__ = ["search", "metrics", "orders_summary", "bookings_funnel"]


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {API_OK_KEY: True, API_DATA_KEY: data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": message}}


def _require_str(v: Any, name: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{name} required")
    return v.strip()


def _parse_iso_utc(s: str) -> datetime:
    s = _require_str(s, "datetime")
    if s.endswith("Z"):
        s = s[:-1] + "00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _bucket_day(dt: datetime) -> str:
    d = dt.astimezone(timezone.utc)
    floored = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return floored.strftime("%Y-%m-%d")


def _month_start(dt: datetime) -> datetime:
    d = dt.astimezone(timezone.utc)
    return datetime(d.year, d.month, 1, tzinfo=timezone.utc)


def _next_month(dt: datetime) -> datetime:
    d = _month_start(dt)
    if d.month == 12:
        return datetime(d.year + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(d.year, d.month + 1, 1, tzinfo=timezone.utc)


def _validate_granularity(g: str) -> str:
    g = _require_str(g, "type").lower()
    if g not in {"daily", "weekly", "monthly"}:
        raise ValueError("type must be one of daily|weekly|monthly")
    return g


def _page_args(page: int, size: int, max_size: int = 100) -> Tuple[int, int]:
    try:
        p = int(page)
    except Exception:
        p = 1
    try:
        s = int(size)
    except Exception:
        s = 20
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > max_size:
        s = max_size
    return p, s 


# -------------------------------------------------------------------------
# Public interface
# -------------------------------------------------------------------------
def search(q: str, page: int = 1, size: int = 20) -> Dict[str, Any]:
    """
    Global admin search across codes / names / phone / email.
    Delegates to repo:search and returns the unified pagination envelope.
    """
    try:
        term = _require_str(q, "q")
        p, s = _page_args(page, size)
        try:
            # Expect repository to return {"items": [...], "total": int, "page": p, "size": s}
            res = repo_search.search(term, page=p, size=s)
        except PyMongoError as e:
            return _err(*_map_pymongo(e))
        except Exception as e:
            # If repository uses differnt error mapping, surface as internal
            return _err(ErrorCode.ERR_INTERNAL.value, str(e))
        
        items = list(res.get("items", []))
        total = int(res.get("total", 0))
        return _ok({"items": items, "total": total, "page": p, "size": s})
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

def metrics(date: str, type: str = "daily") -> Dict[str, Any]:
    """
    Admin metrics window for a given date and granularity.
    Returns rollup buckets for the requested granularity.
    - dailty : [date, date+1]
    - weekly : aligned to Monday 00:00 UTC .. +7d
    - monthly : first day of month 00:00 UTC -- first day next month
    """
    try:
        when = _parse_iso_utc(date)
        gran = _validate_granularity(type)
        
        if gran == "daily":
            start = datetime(when.year, when.month, when.day, tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            sb = _bucket_day(start)
            eb = _bucket_day(end)
        elif gran == "weekly":
            # Monday=0
            d = datetime(when.year, when.month, when.day, tzinfo=timezone.utc)
            monday = d - timedelta(days=(d.weekday() % 7))
            start = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)
            end = start + timedelta(days=7)
            sb = _bucket_day(start)
            eb = _bucket_day(end)
        else:   # monthly
            start = _month_start(when)
            end = _next_month(when)
            sb = _bucket_day(start)
            eb = _bucket_day(end)

        try:
            # Fetch full counters; client can pick specific keys
            items = repo_metrics.query_rollup(gran, sb, eb, keys=None)
        except repo_metrics.RepoError as e:
            return _err(e.code, e.message)
        
        return _ok({"items": items, "total": len(items), "from": sb, "to": eb, "granularity": gran})
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

def orders_summart(from_utc: str, to_utc: str) -> Dict[str, Any]:
    """
    Returns daily time series for orders (created, paid, canceled, expired)
    within [from_utc, to_utc]. Uses rollup collection, not per-row scans.
    """
    try:
        start = _parse_iso_utc(from_utc)
        end = _parse_iso_utc(to_utc)
        if end <= start:
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "to_utc must be greater than from_utc")
        sb = _bucket_day(start)
        eb = _bucket_day(end)

        keys = ["orders.created", "orders.paid", "orders.canceled", "orders.expired"]
        try:
            items = repo_metrics.query_rollup("daily", sb, eb, keys=keys)
        except repo_metrics.RepoError as e:
            return _err(e.code, e.message)
        
        series = []
        for it in items:
            counters = it.get("counters") or {}
            row = {
                "bucket": it.get("bucket"),
                "created": _nested_get(counters, ["orders", "created"]),
                "paid": _nested_get(counters, ["orders", "paid"]),
                "canceled": _nested_get(counters, ["orders", "canceled"]),
                "expired": _nested_get(counters, ["orders", "expired"])
            }
            series.append(row)

        return _ok({"series": series, "from": sb, "to": eb, "granularity": "daily"})
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

def booking_funnel(from_utc: str, to_utc: str) -> Dict[str, Any]:
    """
    Returns daily time series for bookings funnel:
    requested, confirmed, canceled, completed, no_show.
    """
    try:
        start = _parse_iso_utc(from_utc)
        end = _parse_iso_utc(to_utc)
        if end <= start:
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "to_utc must be greater than from_utc")
        sb = _bucket_day(start)
        eb = _bucket_day(end)

        keys = [
            "bookings.requested",
            "bookings.confirmed",
            "bookings.canceled",
            "bookings.completed",
            "bookings.no_show"
        ]
        try:
            items = repo_metrics.query_rollup("daily", sb, eb, keys=keys)
        except repo_metrics.RepoError as e:
            return _err(e.code, e.message)
        
        series = []
        for it in items:
            counters = it.get("counters") or {}
            row = {
                "bucket": it.get("bucket"),
                "requested": _nested_get(counters, ["bookings", "requested"]),
                "confirmed": _nested_get(counters, ["bookings", "confirmed"]),
                "canceled": _nested_get(counters, ["bookings", "canceled"]),
                "completed": _nested_get(counters, ["bookings", "completed"]),
                "no_show": _nested_get(counters, ["bookings", "no_show"])
            }
            series.append(row)

        return _ok({"series": series, "from": sb, "to": eb, "granularity": "daily"})
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

# -------------------------------------------------------------------------
# Internal utilites
# -------------------------------------------------------------------------
def _nested_get(d: Dict[str, Any], path: List[str]) -> int:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return 0
        cur = cur[p]
    try:
        return int(cur)
    except Exception:
        return 0
    

def _map_pymongo(e: PyMongoError) -> Tuple[str, str]:
    # Fallback mapping when a repository does not expose its own mapper.
    # Treat al backend errors as internal to avoid leaking details.
    return ErrorCode.ERR_INTERNAL.value, str(e)
