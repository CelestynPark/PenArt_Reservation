from __future__ import annotations

import base64
import hmac
import os
import time
from hashlib import sha256
from typing import List

from flask import current_app, session
from werkzeug.exceptions import Forbidden

from app.core.constants import ErrorCode

CSRF_TTL_SECONDS = 7200  # 2h
_CSRF_SESSION_SALT_KEY = "_csrf_salt"
_CSRF_USED_NONCES_KEY = "_csrf_used_nonces"
_CSRF_VERSION = "v1"


class SecurityError(Forbidden):
    def __init__(self, description: str = "Forbidden"):
        super().__init__(description=description)
        self.error_code = ErrorCode.FORBIDDEN


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _get_secret_key() -> bytes:
    key = current_app.config.get("SECRET_KEY") or ""
    if not isinstance(key, (bytes, bytearray)):
        key = key.encode("utf-8")
    if not key:
        raise RuntimeError("SECRET_KEY is not configured")
    return bytes(key)


def rand_token(n: int = 32) -> str:
    return _b64url(os.urandom(max(16, int(n))))


def sign(data: bytes) -> str:
    return _b64url(hmac.new(_get_secret_key(), data, sha256).digest())


def verify(sig: str, data: bytes) -> bool:
    try:
        expected = sign(data)
        return hmac.compare_digest(expected, sig)
    except Exception:
        return False


def _ensure_session_salt() -> str:
    salt = session.get(_CSRF_SESSION_SALT_KEY)
    if not salt:
        salt = rand_token(32)
        session[_CSRF_SESSION_SALT_KEY] = salt
    return salt


def _add_used_nonce(nonce: str) -> None:
    used: List[str] = session.get(_CSRF_USED_NONCES_KEY, [])
    if nonce in used:
        raise SecurityError("CSRF token replay detected")
    used.append(nonce)
    # cap size to avoid unbounded growth
    if len(used) > 50:
        used = used[-50:]
    session[_CSRF_USED_NONCES_KEY] = used


def generate_csrf() -> str:
    salt = _ensure_session_salt()
    iat = str(int(time.time()))
    nonce = rand_token(16)
    payload = f"{_CSRF_VERSION}|{iat}|{nonce}|{salt}".encode("utf-8")
    sig = sign(payload)
    return ".".join([_CSRF_VERSION, iat, nonce, sig])


def validate_csrf(token: str) -> None:
    if not token or token.count(".") != 3:
        raise SecurityError("Invalid CSRF token format")
    ver, iat_s, nonce, sig = token.split(".", 3)
    if ver != _CSRF_VERSION:
        raise SecurityError("CSRF token version mismatch")
    try:
        iat = int(iat_s)
    except ValueError:
        raise SecurityError("Invalid CSRF timestamp")
    now = int(time.time())
    if now - iat > CSRF_TTL_SECONDS or iat > now + 60:
        raise SecurityError("CSRF token expired")
    salt = _ensure_session_salt()
    payload = f"{ver}|{iat_s}|{nonce}|{salt}".encode("utf-8")
    if not verify(sig, payload):
        raise SecurityError("CSRF signature invalid")
    _add_used_nonce(nonce)
