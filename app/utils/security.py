from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional, Tuple

from flask import Response

from app.config import load_config

__all__ = [
    "generate_csrf",
    "verify_csrf",
    "sign",
    "verify",
    "hash_password",
    "check_password",
    "set_secure_cookie",
]

_COOKIE_NAME = "csrf_token"
_HEADER_NAME = "X-CSRF-Token"
_CSRF_TTL_SECONDS = 7200
_PBKDF2_ITER = 200_000
_PBKDF2_ALGO = "sha256"
_SALT_LEN = 16


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(data: str) -> bytes:
    pad = "=" * ((4 - (len(data) % 4)) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def _key() -> bytes:
    return load_config().secret_key.encode("utf-8")


def _hmac(data: bytes) -> bytes:
    return hmac.new(_key(), data, hashlib.sha256).digest()


def _ts() -> int:
    return int(time.time())


def sign(value: str) -> str:
    msg = value.encode("utf-8")
    mac = _hmac(msg)
    return _b64u(mac)


def verify(value: str, signature: str) -> bool:
    try:
        expect = _hmac(value.encode("utf-8"))
        got = _b64u_decode(signature)
        return hmac.compare_digest(expect, got)
    except Exception:
        return False


def generate_csrf(session_id: str) -> str:
    ts = str(_ts())
    nonce = _b64u(secrets.token_bytes(16))
    payload = f"{session_id}.{ts}.{nonce}"
    sig = sign(payload)
    token = f"{_b64u(payload.encode('utf-8'))}.{sig}"
    return token


def _parse_csrf(token: str) -> Optional[Tuple[str, int, str, str]]:
    try:
        enc_payload, sig = token.split(".", 1)
        payload = _b64u_decode(enc_payload).decode("utf-8")
        session_id, ts_str, nonce = payload.split(".", 2)
        ts = int(ts_str)
        return session_id, ts, nonce, sig
    except Exception:
        return None


def verify_csrf(session_id: str, token: str) -> bool:
    parsed = _parse_csrf(token)
    if not parsed:
        return False
    sid, ts, _nonce, sig = parsed
    if sid != session_id:
        return False
    if _ts() - ts > _CSRF_TTL_SECONDS:
        return False
    payload = f"{sid}.{ts}.{_nonce}"
    return verify(payload, sig)


def hash_password(pw: str) -> str:
    salt = os.urandom(_SALT_LEN)
    dk = hashlib.pbkdf2_hmac(_PBKDF2_ALGO, pw.encode("utf-8"), salt, _PBKDF2_ITER, dklen=32)
    return f"pbkdf2-${_PBKDF2_ALGO}${_PBKDF2_ITER}${_b64u(salt)}${_b64u(dk)}"


def check_password(pw: str, hashed: str) -> bool:
    try:
        scheme, algo, iter_s, salt_b64, dk_b64 = hashed.split("$", 4)
        if scheme != "pbkdf2-" or algo != _PBKDF2_ALGO:
            return False
        iters = int(iter_s)
        salt = _b64u_decode(salt_b64)
        dk_expect = _b64u_decode(dk_b64)
        dk = hashlib.pbkdf2_hmac(algo, pw.encode("utf-8"), salt, iters, dklen=len(dk_expect))
        return hmac.compare_digest(dk, dk_expect)
    except Exception:
        return False


def set_secure_cookie(resp: Response, name: str, value: str, max_age: int | None = None) -> None:
    resp.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="Lax",
        path="/",
    )

# Convenience exports for consumers expecting the agreed names
COOKIE_NAME = _COOKIE_NAME
HEADER_NAME = _HEADER_NAME
CSRF_TTL_SECONDS = _CSRF_TTL_SECONDS
