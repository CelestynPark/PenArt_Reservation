from __future__ import annotations

from functools import wraps
from typing import Any, Callable, Dict, Optional, TypedDict

from flask import Response, g, jsonify, request

from app.config import load_config
from app.utils.rate_limit import RateLimitError, check_rate_limit, rate_limit_key, remaining
from app.utils.security import COOKIE_NAME as CSRF_COOKIE_NAME
from app.utils.security import HEADER_NAME as CSRF_HEADER_NAME
from app.utils.security import verify_csrf

__all__ = [
    "require_login",
    "require_admin",
    "csrf_protect",
    "apply_rate_limit",
    "current_user",
]


class User(TypedDict):
    id: str
    role: str  # "customer" | "admin"


def _json_error(code: str, message: str, http_status: int) -> Response:
    resp = jsonify({"ok": False, "error": {"code": code, "message": message}})
    resp.status_code = http_status
    return resp


def _unauthorized(message: str = "Authentication required") -> Response:
    return _json_error("ERR_UNAUTHORIZED", message, 401)


def _forbidden(message: str = "Forbidden") -> Response:
    return _json_error("ERR_FORBIDDEN", message, 403)


def _rate_limited(message: str = "Too many requests") -> Response:
    return _json_error("ERR_RATE_LIMIT", message, 429)


def current_user() -> Optional[User]:
    if getattr(g, "user", None):
        return g.user  # type: ignore[return-value]
    # Soft sources for tests/dev:
    uid = (
        request.headers.get("X-User-Id")
        or request.cookies.get("uid")
        or request.cookies.get("session_id")
        or None
    )
    role = (
        request.headers.get("X-User-Role")
        or request.cookies.get("role")
        or request.headers.get("X-Role")
        or None
    )
    if uid and role:
        user: User = {"id": uid, "role": role}
        g.user = user  # cache for request
        return user
    return None


def require_login(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        user = current_user()
        if not user:
            return _unauthorized()
        return fn(*args, **kwargs)

    return wrapper


def require_admin(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        user = current_user()
        if not user:
            return _unauthorized()
        if (user.get("role") or "").lower() != "admin":
            return _forbidden("Admin only")
        return fn(*args, **kwargs)

    return wrapper


def csrf_protect(fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        method = (request.method or "GET").upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            # Double-submit: SameSite cookie + header
            header_token = request.headers.get(CSRF_HEADER_NAME, "")
            cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
            if not header_token or not cookie_token:
                return _forbidden("Missing CSRF token")
            if header_token != cookie_token:
                return _forbidden("Bad CSRF token")
            # Bind token to session_id (or uid)
            sid = (
                request.cookies.get("session_id")
                or request.headers.get("X-Session-Id")
                or request.cookies.get("uid")
                or ""
            )
            if not sid or not verify_csrf(sid, header_token):
                return _forbidden("Invalid CSRF token")
        return fn(*args, **kwargs)

    return wrapper


def apply_rate_limit(fn: Callable[..., Any], limit: Optional[int] = None) -> Callable[..., Any]:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        cfg = load_config()
        user = current_user()
        user_id = (user or {}).get("id")
        ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "-"
        key = rate_limit_key(ip, user_id)
        try:
            check_rate_limit(key, cfg.rate_limit_per_min if limit is None else limit)
        except RateLimitError as e:
            resp = _rate_limited(str(e))
            try:
                rem = remaining(key, cfg.rate_limit_per_min if limit is None else limit)
                resp.headers["X-RateLimit-Remaining"] = str(rem)
            except Exception:
                pass
            return resp
        resp = fn(*args, **kwargs)
        try:
            rem = remaining(key, cfg.rate_limit_per_min if limit is None else limit)
            if isinstance(resp, Response):
                resp.headers["X-RateLimit-Remaining"] = str(rem)
        except Exception:
            pass
        return resp

    return wrapper
