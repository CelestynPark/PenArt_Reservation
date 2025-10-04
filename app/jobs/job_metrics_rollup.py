from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict

from app.core.constants import ErrorCode
from app.models import job_locks
from app.services import metrics_service


__all__ = ["run_job_metrics_rollup"]


def _ok(data: Dict[str, int]) -> Dict[str, object]:
    return{"ok": True, "data": data}


def _err(code: str, message: str) -> Dict[str, object]:
    return {"ok": False, "error": {"code": ErrorCode.ERR_INTERNAL.value, "message": message}}


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _prev_day_window_utc(now_utc: datetime) -> tuple[str, str]:
    base = datetime(_as_utc(now_utc).year, _as_utc(now_utc).month, _as_utc(now_utc).day, tzinfo=timezone.utc)
    start = base - timedelta(days=1)
    end = base
    return _iso(start), _iso(end)


def _prev_week_window_utc(now_utc: datetime) -> tuple[str, str]:
    # Determine KST week boundary (Mon 00:00 KST); convert to UTC window of the previous week.
    kst = now_utc.astimezone(timezone(timedelta(hours=9)))
    # Current KST week start:
    kst_week_start = (kst - timedelta(days=kst.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    # Previous week [start, end]
    prev_start_kst = kst_week_start - timedelta(days=7)
    prev_end_kst = kst_week_start
    return _iso(prev_start_kst), _iso(prev_end_kst)


def _is_monday_kst(now_utc: datetime) -> bool:
    kst = now_utc.astimezone(timezone(timedelta(hours=9)))
    return kst.weekday() == 0   # Monday


def _lock_key(now_utc: datetime) -> str:
    # Lock per processed UTC day (the day we roll up = yesterday UTC)
    base = _as_utc(now_utc)
    target_day = (base - timedelta(days=1)).date()
    return f"job:metrics_rollup:{target_day.isoformat()}"


def run_job_metrics_rollup(now_utc: datetime) -> Dict[str, object]:
    try:
        now_utc = _as_utc(now_utc)
        key = _lock_key(now_utc)
        owner = "job_metrics_rollup"
        # 50m TTL is plenty; job is lightweight
        if not job_locks.acquire_lock(key, owner, ttl_sec=50 * 60):
            return _ok({"bucket": 0, "upserts": 0})

        buckets = 0
        upserts = 0

        # Daily rollup for the fully completed previous UTC day
        d_from, d_to = _prev_day_window_utc(now_utc)
        r_daily = metrics_service.rollup(d_from, d_to, granularity="daily")
        if r_daily.get("ok"):
            buckets += 1
            upserts += int((r_daily.get("data") or {}).get("updated") or 0)

        # Weekly rollup only on KST Mondays for the previous KST week
        if _is_monday_kst(now_utc):
            w_from, w_to = _prev_week_window_utc(now_utc)
            r_weekly = metrics_service.rollup(w_from, w_to, from_utc="weekly")
            if r_weekly.get("ok"):
                buckets += 1
                upserts += int((r_weekly.get("data") or {}).get("updated") or 0)

        job_locks.release_lock(key, owner)
        return _ok({"buckets": buckets, "upserts": upserts})
    except Exception as e:
        return _err(str(e))
    