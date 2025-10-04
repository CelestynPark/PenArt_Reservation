from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import pytz
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import load_config
from app.extensions import get_scheduler, init_extensions
from app.models import job_locks    # ensure TTL model is imported/initialized
from app.jobs import (
    job_reminder,
    job_stale_cleanup,
    job_auto_complete,
    job_order_expire,
    job_metrics_rollup
)

__all__ = ["init_scheduler", "register_jobs"]

TIMEZONE = "Asia/Seoul"


@dataclass(frozen=True)
class JobSpec:
    id: str
    key: str
    func: Callable[[], Dict[str, Any]]
    trigger: str    # "cron" | "interval"
    cron: Optional[Dict[str, Any]] = None
    interval: Optional[Dict[str, Any]] = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _wrap(fn: Callable[[datetime], Dict[str, Any]]) -> Callable[[], Dict[str, Any]]:
    def _inner() -> Dict[str, Any]:
        return fn(_now_utc())
    
    return _inner


def _job_specs(cfg) -> List[JobSpec]:
    tz = pytz.timezone(cfg.timezone or TIMEZONE)

    return [
        JobSpec(
            id="job.reminder",
            key="job:reminder",
            func=_wrap(job_reminder.run_job_reminder),
            trigger="cron",
            cron={"minute": "*/5", "timezone": tz}
        ),
        JobSpec(
            id="job.stale_cleanup",
            key="job:stale_cleanup", 
            func=_wrap(job_stale_cleanup.run_job_stale_cleanup),
            trigger="cron",
            cron={"hour": "3", "minute": "30", "timezone": tz}, # daily 03:30 KST
        ),
        JobSpec(
            id="job.auto_complete",
            key="job:auto_complete",
            func=_wrap(job_auto_complete.run_job_auto_complete),
            trigger="interval",
            interval={"minutes": 15}
        ),
        JobSpec(
            id="job.order_expire",
            key="job:order_expire",
            func=_wrap(job_auto_complete.run_job_auto_complete),
            trigger="cron",
            interval={"minutes": "*/10", "timezone": tz}
        ),
        JobSpec(
            id="job.metrics_rollup_daily",
            key="job:metrics_rollup",
            func=_wrap(job_auto_complete.run_job_auto_complete),
            trigger="cron",
            interval={"hour": "2", "minute": "0", "timezone": tz}   # daily 02:00 kST
        )
    ]


def _ensure_scheduler_timezone(scheduler) -> None:
    tz = pytz.timezone(load_config().timezone or TIMEZONE)
    # apscheduler BackgoundScheduler stores timezone on creation; here we just assert/adjust triggers use tz.
    # Nothing else required; triggers below always pass timezone explicitly where relevent.
    _ = tz  # no-op to satisfy linters


def _init_job_lock_ttl() -> None:
    # The TTL index is defined in app/models/job_locks.py.
    # Nothing to do at runtime because Mongo handles TTL automatically.
    # For the in-memory fallback used in tests, touching the module is enough.
    job_locks.is_locked("bootstrap:noop")   # triggers internal cleanup path safely


def register_jobs(scheduler=None) -> Dict[str, Any]:
    cfg = load_config()
    scheduler = scheduler or get_scheduler()
    _ensure_scheduler_timezone(scheduler)
    _init_job_lock_ttl()

    registered: List[str] = []
    for spec in _job_specs(cfg):
        trigger = None
        if spec.trigger == "cron" and spec.cron:
            trigger = CronTrigger(**spec.cron)
        elif spec.trigger == "interval" and spec.interval:
            trigger = IntervalTrigger(**spec.interval)
        else:
            continue

        scheduler.add_job(
            id=spec.id,
            func=spec.func,
            trigger=trigger,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300
        )
        registered.append(spec.id)

    return {"ok": True, "data": {"registered": registered}}


def init_scheduler(app=None) -> Dict[str, Any]:
    if app is not None:
        init_extensions(app)    # ensures scheduler & mongo are initialized
        scheduler = get_scheduler()
        return register_jobs(scheduler)
    
    