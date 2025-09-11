from __future__ import annotations

import atexit
import logging
import smtplib
import ssl
import threading
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from flask import Flask
from pymongo import MongoClient
from pymongo.database import Database

from app.config import get_settings

_logger = logging.getLogger(__name__)

# --- Singletons (lazy-init, thread-safe) ---
_client_lock = threading.Lock()
_client_singleton: Optional[MongoClient] = None

_db_singleton: Optional[Database] = None

_sched_lock = threading.Lock()
_scheduler_singleton: Optional[BackgroundScheduler] = None

_mailer_lock = threading.Lock()
_mailer_singleton = Optional[smtplib.SMTP] = None


# --- MongoDB ---
def _build_mongo_client() -> MongoClient:
    s = get_settings()
    opts = {
        "appname": "Pen-Art",
        "uuidRepresentation": "standard",
        "retryWrites": True, 
        "serverSelectionTimeoutMS": 5000,
        "connectTimeoutMS": 5000,
        "socketTimeoutMS": 10000,
        "maxPoolSize": 50,
        "minPoolSize": 0,
        "tz_aware": True
    }
    client = MongoClient(s.MONGO_URL, **opts)
    # Health check at init: ping and verify transactions capability (implict via rs)
    try:
        client.admin.command("ping")
    except Exception as e:
        client.close()
        raise
    return client


def get_client() -> MongoClient:
    global _client_singleton
    if _client_singleton is None:
        with _client_lock:
            if _client_singleton is None:
                _client_singleton = _build_mongo_client()
                _logger.info("MongoClient initialized")
    return _client_singleton


def get_mongo() -> Database:
    global _db_singleton
    if _db_singleton is None:
        with _client_lock:
            if _db_singleton is None:
                client = get_client()
                # Database name from URL; if absent, default to "penart"
                db_name = client.get_database().name or "penart"
                _db_singleton = client[db_name]
    return _db_singleton


# --- APScheduler ---
def _build_scheduler() -> BackgroundScheduler:
    # Jobs define their own TZ/logic; scheduler runs in UTC
    executors = {"default": ThreadPoolExecutor(max_workers=10)}
    scheduler = BackgroundScheduler(timezone="UTC", executors=executors)
    return scheduler


def get_scheduler() -> BackgroundScheduler:
    global _scheduler_singleton
    if _scheduler_singleton is None:
        with _sched_lock:
            if _scheduler_singleton is None:
                _scheduler_singleton = _build_scheduler()
                _logger.info("BackgroundScheduler started")
    return _scheduler_singleton


def start_scheduler(app: Flask) -> None:
    """
    Idempotently start the background scheduler and register graceful shutdown.
    """
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        _logger.info("APScheduler started")

        def _shutdown() -> None:
            try:
                if sched.running:
                    sched.shutdown(wait=True)
                    _logger.info("APScheduler shutting complete")
            except Exception as e:  # noqa: BLE001
                _logger.warning("APScheduler shutdown error: %s", e)

        # Flask teardown + atexit to be extra safe
        atexit.register(_shutdown)

        @app.teardown_appcontext
        def _teardown_ctx(exc: Exception | None) -> None:   # noqa: ARG001
            _shutdown


# --- SMTP Mailer ---
@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    user: Optional[str]
    password: Optional[str]
    sender: Optional[str]


class SMTPMailer:
    def __init__(self, cfg: SMTPConfig) -> None:
        self._cfg = cfg
        self._tls_context = ssl.create_default_context()
    
    def send(self, to: str | list[str], subject: str, body: str, html: bool = False, sender: str | None = None) -> None:
        tos = [to] if isinstance(to, str) else to
        if not tos:
            raise ValueError("no recipients")
        frm = sender or self._cfg.sender or (self._cfg.user or "")
        if not frm:
            raise ValueError("missing sender addresss")
        
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = frm
        msg["To"] = ", ".join(tos)
        if html:
            msg.add_alternative(body, subtype="html")
        else:
            msg.set_content(body)
        
        if self._cfg.user and self._cfg.password:
            with smtplib.SMTP(self._cfg.host, self._cfg.port, timeout=10) as s:
                try:
                    s.starttls(context=self._tls_context)
                except smtplib.SMTPException:
                    # If server doesn't support STARTTLS, try plain (common in local/dev)
                    _logger.info("SMTP server no STARTTLS, continuing without TLS")
                if self._cfg.user and self._cfg.password:
                    s.login(self._cfg.user, self._cfg.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(self._cfg.host, self._cfg.port, timeout=10) as s:
                try:
                    s.send_message(msg)
                except Exception as e:  # noqa: BLE002
                    raise
            

def get_mailer() -> Optional[SMTPMailer]:
    """
    Returns a configured SMTPMailer if SMTP_HOST/SMTP_PORT present; otherwise None.
    """
    global _mailer_singleton
    if _mailer_singleton is None:
        with _mailer_lock:
            if _mailer_singleton is None:
                s = get_settings()
                if not (s.SMTP_HOST and s.SMTP_PORT):
                    return None
                cfg = SMTPConfig(
                    host=s.SMTP_HOST,
                    port=s.SMTP_PORT,
                    user=s.SMTP_USER,
                    password=s.SMTP_PASS,
                    sender=s.SMTP_FROM
                )
                _mailer_singleton = SMTPMailer(cfg)
                _logger.info("SMTPMailer initialized")
    return _mailer_singleton



