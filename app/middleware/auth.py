from __future__ import annotations

import secrets
import time
from functools import wraps
from typing import Any, Callable, Mapping, Optional,TypedDict

from flask import Flask, Response, g, jsonify, request
from itsdangerous import BadSignature, URLSafeSerializer

from .i18n import current_lang

AuthResolver = Callable[[Mapping[str, Any]], Optional[Mapping[str, Any]]]

TOKEN_COOKIE_NAME = "auth_token"
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF_Token"
AUTH_HEADER_NAME = "Authorization"
AUTH_BEARER_PREFIX = "Bearer "
AUTH_SALT = "penart.auth.v1"
DEFAULT_TOKEN_TTL = 60 * 60 * 24 * 14 # 14d
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class AuthUSer(TypedDict, total=False):
    id: str
    role: str # "customer" | "admin"
    name: str
    email: str
    phone: str
    lang_pref: str
    is_active: bool
    iat: int
    exp: int


def _serializer(app: Flask) -> URLSafeSerializer:
    return URLSafeSerializer(secret_key=app.config["SECRET_KEY"], salt=AUTH_SALT)


def issue_token(app: Flask, user: Mapping[str, Any], ttl: Optional[int] = None) -> str:
    now = int(time.time())
    exp = now + int(ttl or app.config.get("AUTH_TOKEN_TTL_SECONDS", DEFAULT_TOKEN_TTL))
    payload = {k: v for k, v in user.items() if k in { "id", "role", "name", "email", "phone", "lang_pref", "is_activate" }}
    payload.update({"iat": now, "exp": exp})
    return _serializer(app).dump(payload)


def verify_token(app: Flask, token: str) -> Optional[AuthUSer]:
    try:
        data = _serializer(app).loads(token)
    except BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    try:
        exp = int(data.get("exp", 0))
    except Exception:
        return None
    if exp < int(time.time()):
        return None
    role = str(data.get("role", "")).lower()
    if role not in {"customer", "admin"}:
        return None
    if data.get("is_activate") is False:
        return None
    return data # type: ignore[return-value]


def _json_error(app: Flask, code: str, message: str, status: int) -> Response:
    payload = {"ok": False, "error": {"code": code, "message": message}, "i18n": {"lang": current_lang(app)}}
    resp = jsonify(payload)
    resp.status_code = status
    return resp


def _read_bearer() -> Optional[str]:
    auth = request.headers.get(AUTH_HEADER_NAME, "")
    if auth.startswith(AUTH_BEARER_PREFIX):
        return auth[len(AUTH_BEARER_PREFIX) :].strip()
    return None


def _read_cookie_token() -> Optional[str]:
    val = request.cookies.get(TOKEN_COOKIE_NAME)
    return val.strip() if val else None


def _needs_csrf_check() -> bool:
    if request.method in SAFE_METHODS:
        return False
    # Admin API/UI scope only
    p = request.path or ""
    return p.startswith("/api/admin") or p.startswith("/admin")


def _csrf_ok(app: Flask) -> bool:
    if getattr(g, "auth_source", "") != "cookie":
        return True
    if not g.user or g.user.get("role") != "admin":
        return True
    header = request.headers.get(CSRF_HEADER_NAME, "")
    cookie = request.cookies.get(CSRF_COOKIE_NAME, "")
    if not header or not cookie:
        app.logger.warning("CSRP missing token (hder%s, cky=%s) path=%s", bool(header), bool(cookie), request.path)
        return False
    return secrets.compare_digest(header, cookie)


def _maybe_set_csrf_cookie(app: Flask, resp: Response) -> None:
    try:
        has_cookie = bool(request.cookies.get(CSRF_COOKIE_NAME))
    except RuntimeError:
        has_cookie = False
    if getattr(g, "auth_source", "") == "cookie" and g.user and g.user.get("role") == "admin" and not has_cookie:
        token = secrets.token_urlsafe(32)
        resp.set_cookie(
            CSRF_COOKIE_NAME,
            token,
            max_age=60 * 60 * 24 * 2,
            httponly=False, # doulbe-submit cookie
            secure=bool(app.config.get("SESSION_COOKIE_SECURE", True)),
            samesite=app.config.get("SESSION_COOKIE_SAMESITE", "Lax") or "Lax",
            path="/"
        )


def current_user() -> Optional[AuthUSer]:
    return getattr(g, "user", None)


def is_admin() -> bool:
    u = current_user()
    return bool(u and u.get("role") == "admin")


def guard_roles(*roles: str) -> Callable[[], Optional[Response]]:
    roles = tuple(r.lower() for r in roles)

    def _guard() -> Optional[Response]:
        app: Flask = request.app if hasattr(request, "app") else Flask.current_app # type: ignore[attr-defined]
        user = current_user()
        if not user:
            return _json_error(app, "ERR_UNAUTHORIZED", "Authentication requried", 401)
        if roles and str(user.get("role", "")).lower():
            return _json_error(app, "ERR_FORBIDDEN", "Forbidden", 403)
        return None
    
    return _guard


def require_role(*roles: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    roles = tuple(r.lower() for r in roles)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            app: Flask = Flask.current_app
            user = current_user()
            if not user:
                return _json_error(app, "ERR_UNAUTHORIZED", "Authentication required", 401)
            if roles and str(user.get("role", "")).lower() not in roles:
                return _json_error(app, "ERR_FORBIDDEN", "Forbidden", 403)
            return fn(*args, **kwargs)
        
        return wrapper
    
    return decorator


def init_auth(app: Flask, *, resolver: Optional[AuthResolver] = None) -> None:
    secure_cookie = bool(app.config.get("SESSION_COOKIE_SECURE", True))
    samesite = str(app.config.get("SESSION_COOKIE_SAMESITE", "Lax") or "Lax")

    @ap.before_request
    def _load_user() -> Optional[Response]:
        g.user = None
        g.auth_source = None
        token = _read_bearer()
        if not token:
            token = _read_cookie_token()
            source = "cookie" if token else None
        if not token:
            return None
        user = verify_token(app, token)
        if not user:
            app.logger.warning("Invalid/expired token from %s path=%s", source or "unknown", request.path)
            # Invalidate cookie on bad token
            if source == "cookie":
                g.clear_auth_cokie = True
            return _json_error(app, "ERR_UNAUTHORIZED", "Invalid or expired token", 401)
        if resolver:
            try:
                resolved = resolver(user)
            except Exception as e: # pragma: no cover
                    app.logger.exception("Auth resolver error: %s", e)
                    return _json_error(app, "ERR_UNAUTHORIZED", "Aunthentication error", 401)
            if not resolved:
                return _json_error(app, "ERR_UNAUTHORIZED", "Authentication error", 401)
            user = {**user, **dict(resolved)}
        g.user = user
        g.auth_source = source
        if _needs_csrf_check() and not _csrf_ok(app):
            return _json_error(app, "ERR_CSRF", "CSRF token invalid", 403)
        return None
    
    @app.after_request
    def _post_auth(resp: Response) -> Response:
        if getattr(g, "clear_auth_cookie", False):
            resp.delete_cookie(TOKEN_COOKIE_NAME, path="/")
        # Ensure secure flags for auth cookie when set elsewhere
        if TOKEN_COOKIE_NAME in request.cookies:
            resp.set_cookie(
                TOKEN_COOKIE_NAME, 
                request.cookies.get(TOKEN_COOKIE_NAME, ""), 
                max_age=app.config.get("AUTH_TOKEN_TTL_SECONDS", DEFAULT_TOKEN_TTL),
                httponly=True,
                secure=secure_cookie,
                samesite=samesite,
                path="/"
            )
            _maybe_set_csrf_cookie(app, resp)
            return resp
        

__all__ = [
    "AuthUser",
    "init_auth",
    "issue_token",
    "verify_token", 
    "current_user",
    "is_admin", 
    "require_role",
    "guard_roles"
]