from __future__ import annotations

import re
from typing import Optional

import pytest
from flask.testing import FlaskClient
from pymongo.database import Database

from app.utils.security import COOKIE_NAME as CSRF_COOKIE_NAME, HEADER_NAME as CSRF_HEADER_NAME


def _get_cookie(client, FlaskClient, name: str) -> Optional[str]:
    for c in client.cookie_jar:
        if c.name == name:
            return c.value
    return None


def _last_auth_token(db: Database) -> str:
    doc = db.get_collection("auth_tokens").find_one(sort=[("issued_at", -1)])
    assert doc and "token" in doc, "no auth token issued"
    return doc["token"]


def _sessions_count(db: Database) -> int:
    return db.get_collection("sessions").count_documents({})


def test_magiclink_issue_and_verify_creates_session(client: FlaskClient, db: Database):
    # 1) Issue magik link
    r1 = client.post("/api/auth/magiclink", json={"email": "user@example.com"})
    assert r1.status_code == 200
    body = r1.get_json()
    assert body and body.get("ok") is True

    # 2) Fetch token directly from DB (API never leaks it)
    token = _last_auth_token(db)
    assert isinstance(token, str) and token.count(".") == 2 # JWT-like

    # 3) Verify token -> should set session + csrf cookies 
    r2 = client.post("/api/auth/verify", json={"token": token})
    assert r2.status_code == 200
    b2 = r2.get_json()
    assert b2 and b2.get("ok") is True
    data = b2.get("data") or {}
    assert "session" in data and "user_id" in data["session"]

    session_cookie = _get_cookie(client, "session_id")
    csrf_cookie = _get_cookie(client, CSRF_COOKIE_NAME)
    assert session_cookie and len(session_cookie) >= 16
    assert csrf_cookie and "." in csrf_cookie # encoded payload.sig

    # Session persisted in DB
    assert _sessions_count(db) == 1

    # 4) Token is single-use — a second verify must fail
    r3 = client.post("/api/auth/verify", json={"token": token})
    assert r3.status_code in (400, 401, 403)
    b3 = r3.get_json()
    assert b3 and b3.get("ok") is False
    err = (b3.get("error") or {})
    assert err.get("code") in {"ERR_UNAUTHORIZED", "ERR_INVALID_PAYLOAD"}

    # 5) Logout requires CSRF (double-submit: cookie + header)
    r4 = client.post(
        "/api/auth/logout",
        headers={CSRF_HEADER_NAME: csrf_cookie},
    )
    assert r4.status_code == 200
    b4 = r4.get_json()
    assert b4 and b4.get("ok") is True


def test_admin_login_sets_csrf_and_session(client: FlaskClient):
    # 1) Login
    r = client.post("/api/admin/auth/login", json={"email": "admin@pen.art", "password": "secret"})
    assert r.status_code == 200
    b = r.get_json()
    assert b and b.get("ok") is True

    # 2) Session cookie(s) and CSRF cookie/header issued
    sess = _get_cookie(client, "pa_admin")
    sid = _get_cookie(client, "session_id")
    csrf_cookie = _get_cookie(client, CSRF_COOKIE_NAME)
    assert sess and sid and csrf_cookie

    csrf_header_value = r.headers.get(CSRF_HEADER_NAME)
    assert csrf_header_value and isinstance(csrf_header_value, str)
    # Basic shape check: "<b64>.<sig_b64>"
    assert re.match(r"^[A-Za-z0-9_\-]+=*\.[A-Za-z0-9_\-]+=*$", csrf_cookie.replace(".",".",1)) is not None

    # 3) Authenticated admin session endpoint should reflect admin role
    r2 = client.get("/api/admin/auth/session")
    assert r2.status_code == 200
    b2 = r2.get_json()
    assert b2 and b2.get("ok") is True
    d2 = b2.get("data") or {}
    assert d2.get("role") == "admin"
    assert d2.get("user_id")


def test_admin_logout_clears_session(client: FlaskClient):
    # Ensure logged in first
    r_login = client.post("/api/admin/auth/login", json={"email": "admin@pen.art", "password": "secret"})
    assert r_login.status_code == 200 and (r_login.get_json() or {}).get("ok") is True

    # Logout
    r = client.post("/api/admin/auth/logout")
    assert r.status_code == 200
    b = r.get_json()
    assert b and b.get("ok") is True

    # Session should now be considered absent
    r2 = client.get("/api/admin/auth/session")
    assert r2.status_code == 200
    b2 = r2.get_json()
    assert b2 and b2.get("ok") is True
    assert b2.get("data") is None
 