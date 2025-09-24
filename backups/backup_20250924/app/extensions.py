from __future__ import annotations

import threading
import time
from typing import Any, Optional
from zoneinfo import ZoneInfo

from flask import Flask
from pymongo import MongoClient, errors as pymongo_errors
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings

__all__ = ["mongo", "cache", "scheduler", "init_extensions"]


class SimpleTTLCache:
    def __init__(self, default_ttl: int = 300):
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = int(default_ttl)
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        now = time.time()
        with self._lock:
            item = self._store.get(key)
            if not item:
                return default
            exp, val = item
            if exp and exp < now:
                self._store.pop(key, None)
                return default
            return val

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl_s = int(ttl if ttl is not None else self._ttl)
        exp = time.time() + ttl_s if ttl_s > 0 else 0.0
        with self._lock:
            self._store[key] = (exp, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


mongo: Optional[MongoClient] = None
cache = SimpleTTLCache()
scheduler: Optional[BackgroundScheduler] = None


def _init_mongo(app: Flask) -> MongoClient:
    global mongo
    if mongo is not None:
        return mongo
    settings = get_settings()
    opts = dict(
        tz_aware=True,
        appname="penart",
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=10000,
        retryWrites=True,
    )
    client = MongoClient(settings.MONGO_URL, **opts)
    try:
        client.admin.command("ping")
    except pymongo_errors.PyMongoError as e:
        app.logger.error("Mongo ping failed: %s", e)
        raise
    mongo = client
    app.extensions["mongo"] = mongo
    app.logger.info("MongoDB connected (pool ready)")
    return mongo


def _init_scheduler(app: Flask) -> BackgroundScheduler:
    global scheduler
    if scheduler is not None and scheduler.running:
        return scheduler
    settings = get_settings()
    tz = ZoneInfo(settings.TIMEZONE or "Asia/Seoul")
    sched = BackgroundScheduler(
        timezone=tz,
        daemon=True,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
    )
    # Register jobs
    try:
        from app.jobs.scheduler import register_jobs  # type: ignore
    except Exception:  # fallback if register function not yet present
        register_jobs = None  # type: ignore

    if register_jobs:
        try:
            register_jobs(sched, app)  # type: ignore[arg-type]
        except Exception as e:
            app.logger.error("Failed to register jobs: %s", e)
            raise

    sched.start()
    scheduler = sched
    app.extensions["scheduler"] = scheduler
    app.logger.info("APScheduler started (tz=%s)", settings.TIMEZONE)
    return scheduler


def init_extensions(app: Flask) -> None:
    _init_mongo(app)
    _init_scheduler(app)
    app.extensions["cache"] = cache

    @app.teardown_appcontext
    def _shutdown_ctx(_exc: Optional[BaseException]) -> None:
        # Keep pooled connections for process lifetime; scheduler is background daemon.
        return None
