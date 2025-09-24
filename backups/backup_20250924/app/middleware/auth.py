from __future__ import annotations

from functools import wraps
from typing import Callable, Optional

from flask import Flask, Request, Response, current_app, g, request

from app.config import get_settings
from app.core.constants import ErrorCode, UserRole
from app.utils.responses import fail
from app.utils.security import SecurityError, validate_csrf

# Auth service contracts
# - SESSION_COOKIE_NAME: str
# - load_session(token: str) -> Optional[dict]   # returns None if invalid/expired
# - logout_session(token: str) -> None           # idempotent
from app.services.auth_service import (  # type: ignore[assignment]
    SESSION_COOKIE_NAME,
    load_session,
    logout_session,
)

__all__ = ["init_auth", "login_required", "admin_required"]


ADMIN_CSRF_EXEMPT = {"/api/admin/auth/login"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _should_check_csrf(req: Request) -> bool:
    if req.method not in UNSAFE_METHODS:
        return False
    if not req.path.startswith("/api/admin"):
        return False
    if req.path in ADMIN_CSRF_EXEMPT:
        return False
    return True


def _extract_csrf(req: Request) -> Optional[str]:
    token = (
        req.headers.get("X-CSRF-Token")
        or req.headers.get("X-Csrf-Token")
        or req.headers.get("X-CSRF")
    )
    if token:
        return token
    if req.mimetype == "application/json":
        data = req.get_json(silent=True) or {}
        return data.get("_csrf")
    if req.form:
        return req.form.get("_csrf")
    return None


def _clear_sid_cookie(resp: Response) -> None:
    settings = get_settings()
    resp.delete_cookie(
        SESSION_COOKIE_NAME, path="/", samesite="Lax", secure=settings.is_production
    )


def _load_current_session() -> None:
    sid = request.cookies.get(SESSION_COOKIE_NAME)
    g.authenticated = False
    g.is_admin = False
    g.user = None
    g.user_id = None
    g.role = None
    g._auth_sid_present = bool(sid)
    g._auth_clear_cookie = False

    if not sid:
        return

    sess = load_session(sid)
    if not sess:
        g._auth_clear_cookie = True
        return

    user = sess.get("user") or {}
    role = (user.get("role") or sess.get("role") or "").lower()
    g.user = user or None
    g.user_id = user.get("id") if user else None
    g.role = role or None
    g.is_admin = role == UserRole.ADMIN.value
    g.authenticated = True


def _maybe_check_csrf() -> Optional[Response]:
    if not _should_check_csrf(request):
        return None
    token = _extract_csrf(request)
    try:
        validate_csrf(token or "")
    except SecurityError as e:
        return fail(e.error_code, str(e), status=403)
    return None


def login_required() -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not getattr(g, "authenticated", False):
                return fail(ErrorCode.UNAUTHORIZED, "인증이 필요합니다.", status=401)
            need = _maybe_check_csrf()
            if need is not None:
                return need
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def admin_required() -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not getattr(g, "authenticated", False):
                return fail(ErrorCode.UNAUTHORIZED, "인증이 필요합니다.", status=401)
            if not getattr(g, "is_admin", False):
                return fail(ErrorCode.FORBIDDEN, "권한이 없습니다.", status=403)
            need = _maybe_check_csrf()
            if need is not None:
                return need
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def init_auth(app: Flask) -> None:
    settings = get_settings()

    @app.before_request  # type: ignore[misc]
    def _auth_before() -> None:
        _load_current_session()

    @app.after_request  # type: ignore[misc]
    def _auth_after(resp: Response) -> Response:
        # If session cookie existed but session is invalid/expired, log out and clear cookie.
        try:
            if getattr(g, "_auth_sid_present", False) and getattr(
                g, "_auth_clear_cookie", False
            ):
                sid = request.cookies.get(SESSION_COOKIE_NAME)
                if sid:
                    try:
                        logout_session(sid)
                    except Exception:
                        pass
                _clear_sid_cookie(resp)
        except Exception:
            # Never block response due to logout cleanup
            pass

        # Attach Content-Security cookies semantics are handled elsewhere; ensure cookie flags if set here
        # (We do not refresh or set the auth cookie here; that is responsibility of auth_service on login/refresh.)
        return resp
