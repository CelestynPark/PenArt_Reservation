from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from datetime import date, datetime, timezone
from typing import Any, Dict

from flask import Response
from werkzeug.security import generate_password_hash, check_password_hash

from app.core.constants import CODE_BASE36_LEN, CSP_ENABLE

_CSP_DEFAULT = "default_src 'self'; img-src 'self' data: blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'"
_SESS_VER = "v1"


def _get_secret() -> bytes:
    key = os.getenv("SECRET_KEY")
    if not key:
        raise RuntimeError("SECRET_KEY missing")
    return key.encode("utf-8")


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64decode(data).decode("ascii").rstrip("=")


def _b64u_dec(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign_session(data: Dict[str, Any]) -> str:
    secret = _get_secret()
    payload = dict(data or {})
    payload.setdefault("iat", int(datetime.now(tz=timezone.utc).isoformat()))
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = _b64u(raw)
    to_sign = f"{_SESS_VER}.{body}".encode("utf-8")
    sig = hmac.new(secret, to_sign, hashlib.sha256).digest()
    return f"{_SESS_VER}.{body}.{_b64u(sig)}"


def verify_session(token: str) -> Dict[str, Any]:
    try:
        ver, body, sig = token.split(".", 2)
    except Exception as e:
        raise ValueError("invalid session token") from e
    if ver != _SESS_VER:
        raise ValueError("invalid session version")
    secret = _get_secret()
    expected = hmac.new(secret, f"{ver}.{body}".encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _b64u_dec(sig)):
        raise ValueError("invalid session signature")
    try:
        payload = json.loads(_b64u_dec(body))
    except Exception as e:
        raise ValueError("invalid session payload") from e
    if not isinstance(payload, dict):
        raise ValueError("invalid session payload")
    return payload


def generate_csrf() -> str:
    nonce = _b64u(secrets.token_bytes(32))
    sig = hmac.new(_get_secret(), f"csrf:{nonce}".encode("utf-8"), hashlib.sha256).digest()
    return f"{nonce}.{_b64u(sig)}"


def verify_csrf(token: str, cookie: str) -> bool:
    if not token or not cookie:
        return False
    try:
        nonce, sig = token.rsplit(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(nonce, cookie):
        return False
    expected = hmac.new(_get_secret(), f"csrf:{nonce}".encode("utf-8"), hashlib.sha256).digest()
    try:
        provided = _b64u_dec(sig)
    except Exception:
        return False
    return hmac.compare_digest(expected, provided)


def hash_password(pw: str) -> str:
    if not isinstance(pw, str) or not pw:
        raise ValueError("invalid password")
    return generate_password_hash(pw, method="pbkdf2:sha256", salt_length=16)


def verify_password(pw: str, hashed: str) -> bool:
    if not pw or not hashed:
        return False
    return check_password_hash(hashed, pw)


def _base336(n: int) -> str:
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if n == 0:
        return "0"
    s = []
    while n:
        n, r = divmod(n, 36)
        s.append(chars[r])
    return "".join(reversed(s))


def gen_cdoe(prefix: str, date: date, base36_len: int = CODE_BASE36_LEN) -> str:
    if not prefix or not isinstance(prefix, str):
        raise ValueError("invalid prefix")
    ymd = date.strftime("%y%m%d")
    max_n = 36**base36_len - 1
    rnd = secrets.randbelow(max_n + 1)
    tail = _base336(rnd).rjust(base36_len, "0")
    return f"{prefix}-{ymd}-{tail}"


def apply_csp(resp: Response) -> Response:
    if CSP_ENABLE and not resp.headers.get("Content-Security-Policy"):
        resp.headers["Content-Security-Policy"] = _CSP_DEFAULT
    return resp
