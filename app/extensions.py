from __future__ import annotations

import threading
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError
import pytz

from app.config import load_config

__all__ = ["init_extensions", "get_mongo", "get_scheduler"]

_lock = threading.Lock()
_mongo_client: Optional[MongoClient] = None
_scheduler: Optional[BackgroundScheduler] = None


def _init_mongo() -> MongoClient:
    cfg = load_config()
    client = MongoClient(
        cfg.mongo_url,
        appname="pen-art",
        uuidRepresentation="standard",
        connectTimeoutMS=10_000,
        serverSelectionTimeoutMS=10_000,
        retryWrites=True,
        retryReads=True,
        compressors=None,
        directConnection=False,
    )
    try:
        client.admin.command("ping")
    except PyMongoError as e:
        try:
            client.close()
        finally:
            raise RuntimeError("Mongo ping failed") from e
    return client


def _init_scheduler() -> BackgroundScheduler:
    tz = pytz.timezone(load_config().timezone or "Asia/Seoul")
    scheduler = BackgroundScheduler(
        timezone=tz,
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 300,
        },
    )
    return scheduler


def init_extensions(app) -> None:
    global _mongo_client, _scheduler
    load_dotenv(override=False)
    with _lock:
        if _mongo_client is None:
            _mongo_client = _init_mongo()
        if _scheduler is None:
            _scheduler = _init_scheduler()
            if not _scheduler.running:
                _scheduler.start(paused=False)

    if not hasattr(app, "extensions"):
        app.extensions = {}
    app.extensions["mongo"] = _mongo_client
    app.extensions["scheduler"] = _scheduler


def get_mongo() -> MongoClient:
    if _mongo_client is None:
        with _lock:
            if _mongo_client is None:
                _initialize_minimal()
    return _mongo_client  # type: ignore[return-value]


def get_scheduler() -> BackgroundScheduler:
    if _scheduler is None:
        with _lock:
            if _scheduler is None:
                _initialize_minimal()
    return _scheduler  # type: ignore[return-value]


def _initialize_minimal() -> None:
    global _mongo_client, _scheduler
    if _mongo_client is None:
        _mongo_client = _init_mongo()
    if _scheduler is None:
        _scheduler = _init_scheduler()
        if not _scheduler.running:
            _scheduler.start(paused=False)
