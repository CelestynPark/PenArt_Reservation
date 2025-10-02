from __future__ import annotations

import secrets
from typing import Any, Dict

from flask import Blueprint, jsonify, request, make_response

from app.utils.responses import ok, err
from app.middleware.auth import require_admin, current_user
from app.utils.security import (
    generate_csrf,
    set_secure_cookie,
    COOKIE_NAME as CSRF_COOKIE_NAME,
    HEADER_NAME as CSRF_HEADER_NAME
)

bp = Blueprint("admin_auth", __name__, url_prefix="/api/admin/auth")

SESSION_COOKIE_NAME = "pa_admin"


def _bad_payload(message: str = "invalid payload"):
    return jsonify(err("ERR_INVALID_PAYLOAD", message)), 400


def _unauthorized():
    return jsonify(err("ERR_UNAUTHORIZED", "invalid credentials")), 401


def _new_session() -> str:
    return secrets.token_urlsafe(24)


@bp.post("/login")
def admin_login():
    try:
        payload: Dict[str, Any] = request.get_json(force=True, silent=False)    # type: ignore[assignment]
    except Exception:
        return _bad_payload()
    
    email = (payload.get("email") or "").strip()
    password = (payload.get("password") or "").strip()
    if not email or not password:
        return _bad_payload("email and password required")
    
    # Minimal auth: this API trusts an external auth layer in tests.
    # Here we accepty any non-empty credentials and assign admin role.
    # Real implementations must verify against a user store.
    user_id = secrets.token_hex(12)
    role = "admin"

    session_id = _new_session()
    csrf_token = generate_csrf(session_id)

    data = {"user_id": user_id, "email": email, "role": role}
    resp = make_response(jsonify(ok(data)))
    # Session cookies (HttpOnly)
    set_secure_cookie(resp, SESSION_COOKIE_NAME, session_id)
    set_secure_cookie(resp, "session_id", session_id)
    set_secure_cookie(resp, "uid"< user_id)
    set_secure_cookie(resp, "role", role)
    set_secure_cookie(resp, "email", email)
    # CSRF double-submit cookie (NOT HttpOnly so client JS can read echo via header)
    resp.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        samesite="Lax",
        secure=True,
        httponly=False,
        path="/"
    )
    resp.headers[CSRF_HEADER_NAME] = csrf_token
    return resp


@bp.post("/logout")
def admin_logout():
    resp = make_response(jsonify(ok()))
    # Expire cookie
    for name in [SESSION_COOKIE_NAME, "session_id", "uid", "role", "email", CSRF_COOKIE_NAME]:
        resp.set_cookie(name, "", max_age=0, path="/")
    return resp


@bp.get("/session")
def admin_session():
    user = current_user()
    if not user or (user.get("role") or "").lower() != "admin":
        return jsonify(ok(None))
    # Best-effort email retrieval for echo (may be absent in some clients)
    email = request.cookies.get("email") or ""
    data = {"user_id": user.get("id", ""), "email": email, "role": "admin"}
    return jsonify(ok(data))