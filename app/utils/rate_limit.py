from __future__ import annotations

import threading
import time
from typing import Tuple

from flask import make_response, request

from app.core.constants import ERR_RATE_LIMIT
from app.services.i18n_service import get_lang, t
from app.utils.responses import err

_BUCKETS: dict[str, tuple[int, int]] = {}
_LOCK = threading.Lock()


def _now() -> int:
    return int(time.time())


def _window_start(now: int, window_sec: int) -> int:
    return now - (now % window_sec)


def _client_ip() -> str:
    if not request:
        return "0.0.0.0"
    h = request.headers.get("X-Forwarded-For") or request.headers.get("X-Real-IP")
    ip = (h.split(",", 1)[0].strip() if h else None) or (request.remote_addr or "0.0.0.0")
    return ip


def _identify() -> str:
    sid = request.headers.get("sid") if request else None
    if not sid:
        sid = request.cookies.get("session") if request else None
    return sid or _client_ip()


def make_key(scope: str, identify: str | None = None) -> str:
    ident = identify or _identify()
    return f"{scope}:{ident}"


def hit_and_check(key: str, limit: int, window_sec: int) -> Tuple[bool, int]:
    now = _now()
    ws = _window_start(now, window_sec)
    with _LOCK:
        prev = _BUCKETS.get(key)
        if not prev or prev[0] != ws:
            count = 1
        else:
            count = prev[1] + 1
        _BUCKETS[key] = (ws, count)
    allowed = count <= limit
    remaining = max(0, limit - count)
    return allowed, remaining


def _scope_from_path() -> str:
    p = (request.path or "") if request else ""
    if p.startswith("/api/admin"):
        return "admin"
    if p.startswith("/api"):
        return "api"
    return "web"


def rate_limited(limit_per_min: int) -> callable:
    window_sec = 60

    def decorator(fn):
        def wrapper(*args, **kwargs):
            scope = _scope_from_path()
            key = make_key(scope)
            allowed, remaining = hit_and_check(key, limit_per_min, window_sec)
            reset_in = window_sec - (_now() % window_sec)
            if not allowed:
                lang = get_lang()
                r = err(
                    code=ERR_RATE_LIMIT,
                    message=t("error.rate_limited", lang),
                    status=429,
                    lang=lang
                )
                r.headers["Retry-After"] = str(reset_in)
                r.headers["X-RateLimit-Limit"] = str(limit_per_min)
                r.headers["X-RateLimit-Remaining"] = "0"
                return r
            resp = make_response(fn(*args, **kwargs))
            resp.headers["X-RateLimit-Limit"] = str(limit_per_min)
            resp.headers["X-RateLimit-Remaining"] = str(remaining)
            resp.headers["X-RateLimit-Reset"] = str(reset_in)
            return resp
        
        wrapper.__name__ = getattr(fn, "__name__", "rate_limited")
        return wrapper
    
    return decorator
