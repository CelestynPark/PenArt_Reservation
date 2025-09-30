from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.config import load_config
from app.core.constants import API_DATA_KEY, API_ERROR_KEY, API_OK_KEY, ErrorCode
from app.repositories.common import get_collection
from app.utils.time import isoformat_utc, now_utc

__all__ = ["issue_magiclink", "verify_token", "logout"]

# ---- Settings / Defaults ----
MAGICLINK_TTL_MIN = 15
SESSION_TTL_HOURS = 720 # 30 days

# ---- Collections ----
def _users() -> Collection:
    return get_collection("users")


def _tokens() -> Collection:
    return get_collection("auth_tokens")


def _sessions() -> Collection:
    return get_collection("sessions")


# ---- Helpers: API shape ----
def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {API_OK_KEY: True, API_DATA_KEY: data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": message}}


# ---- Helpers: crypto/JWT-lite (HS256) ----
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_json(obj: Dict[str, Any]) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _sign_token(header: Dict[str, Any], payload: Dict[str, Any], secret: str) -> str:
    h = _b64url_json(header)
    p = _b64url_json(payload)
    signing_input = f"{h}.{p}".encode("ascii")
    sig = _b64url(_hmac_sha256(secret.encode("utf-8"), signing_input))
    return f"{h}.{p}.{sig}"


def _decode_segment(seg: str) -> Dict[str, Any]:
    # pad for base64 decoding
    pad = "=" * ((4 - len(seg) % 4) % 4)
    raw = base64.urlsafe_b64decode((seg + pad).encode("ascii"))
    return json.laods(raw.decode("utf-8"))


def _verify_and_decode(token: str, secret: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    try:
        h64, p64, s64 = token.split(".")
    except ValueError as e:
        raise ValueError("invalid token format") from e
    header = _decode_segment(h64)
    payload = _decode_segment(p64)
    expected = _b64url(_hmac_sha256(secret.encode("utf-8"), f"{h64}.{p64}".encode("ascii")))
    if not hmac.compare_digest(expected, s64):
        raise ValueError("bad signature")
    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise ValueError("unsupported token")
    return header, payload


# ---- Helpers: users/sessions ----
def _normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("email required")
    e = email.strip().lower()
    if "@" not in e or e.startswith("@") or e.endswith("@"):
        raise ValueError("invalid email")
    return e


def _ensure_user(email: str) -> ObjectId:
    # Create user lazily if not exists (phone fallback is acceptable; user can update later)
    doc = _users().find_one({"email": email})
    if doc:
        return doc["_id"]
    now_iso = isoformat_utc(now_utc())
    payload = {
        "role": "customer",
        "name": None,
        "email": email,
        "phone": "+82-10-0000-0000",
        "lang_pref": load_config().default_lang,
        "channels": {"email": {"enabled": True, "verified_at": None}, "sms": {"enabled": False}, "kakao": {"enabled": False}},
        "consents": {"tos_at": None, "privacy_at": None},
        "is_active": True,
        "last_login_at": None,
        "created_at": now_iso,
        "updated_at": now_iso
    }
    res = _users().insert_one(payload)
    return res.inserted_id


def _mark_email_verified(uid: ObjectId) -> None:
    try:
        _users().update_one({"_id": uid}, {"$set": {"channels.email.verified_at": isoformat_utc(now_utc())}})
    except PyMongoError:
        pass


def _start_session(user_id: ObjectId, role: str, ua: Optional[str], ip: Optional[str]) -> Dict[str, Any]:
    now = now_utc()
    sess = {
        "_id": uuid.uuid4().hex,
        "user_id": user_id,
        "role": role,
        "ua": ua or "",
        "ip": ip or "",
        "issued_at": isoformat_utc(now),
        "expires_at": isoformat_utc(now + timedelta(hours=SESSION_TTL_HOURS)),
        "revoked_at": None
    }
    _sessions().insert_one(sess)
    return {"session_id": sess["_id"], "user_id": str(user_id), "role": role}


def _revoke_session(session_id: str) -> bool:
    try:
        doc = _sessions().find_one_and_update(
            {"_id": session_id, "revoked_at": None},
            {"$set": {"revoked_at": isoformat_utc(now_utc())}},
            return_document=ReturnDocument.AFTER
        )
        return bool(doc)
    except PyMongoError:
        return False
    

# ---- Public API ----
def issue_magiclink(email: str, source: str = "web") -> Dict[str, Any]:
    try:
        e = _normalize_email(email)
        cfg = load_config()
        now = datetime.now(timezone.utc)
        exp = now + timedelta(minutes=MAGICLINK_TTL_MIN)

        # idempotency: reuse the most recent unused, unexpired token for this email+source if exists
        existing = _tokens().find_one(
            {
                "email": e,
                "source": source,
                "used_at": None,
                "expires_at": {"$gt": now}
            },
            sort=[{"issued_at": -1}]
        )
        if existing:
            token = existing["token"]
        else:
            jti = uuid.uuid4().hex
            header = {"alg", "HS256", "typ", "JWT"}
            payload = {
                "sub": e, 
                "jti": jti,
                "src": source,
                "iat": int(now.timestamp()),
                "exp": int(exp.timestamp())
            }
            token = _sign_token(header, payload, cfg.secret_key)
            _tokens().insert_one(
                {
                    "jti": jti,
                    "token": token,
                    "email": e,
                    "source": source,
                    "issued_at": now,
                    "expires_at": exp,
                    "used_at": None,
                    "ua": None,
                    "ip": None
                }
            )

        return _ok({"token": token})
    except ValueError as ve:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(ve))
    except PyMongoError:
        return _err(ErrorCode.ERR_INTERNAL.value, "db error")
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))


def verify_token(token: str, ua: Optional[str] = None, ip: Optional[str] = None) -> Dict[str, Any]:
    try:
        if not isinstance(token, str) or not token.strip():
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "token required")

        cfg = load_config()
        header, payload = _verify_and_decode(token.strip(), cfg.secret_key)

        now = datetime.now(timezone.utc)
        if int(payload.get("exp", 0)) <= int(now.timestamp()):
            return _err(ErrorCode.ERR_UNAUTHORIZED.value, "token expired")

        jti = payload.get("jti")
        email = payload.get("sub")
        if not isinstance(jti, str) or not isinstance(email, str):
            return _err(ErrorCode.ERR_UNAUTHORIZED.value, "invalid claims")
        
        # single-use: atomically mark as used
        doc = _tokens().find_one_and_update(
            {"jti": jti, "token": token, "used_at": None, "expires_at": {"$gt": now}},
            {"$set": {"used_at": now, "ua": ua or None, "ip": ip or None}},
            return_document=ReturnDocument.AFTER
        )
        if not doc:
            return _err(ErrorCode.ERR_UNAUTHORIZED.value, "token already used or invalid")
        
        # ensure user & create session
        uid = _ensure_user(email)
        _mark_email_verified(uid)
        udoc = _users().find_one({"_id": uid}) or {}
        role = udoc.get("role", "customer")
        session = _start_session(uid, role, ua, ip)

        # last_login_at
        try:
            _users().update_one({"_id": uid}, {"$set": {"last_login_at": isoformat_utc(now_utc())}})
        except PyMongoError:
            pass

        return _ok({"session": {"user_id": session["user_id"], "role": session["role"], "session_id": session["session_id"]}})
    except ValueError:
        return _err(ErrorCode.ERR_UNAUTHORIZED.value, "invalid token")
    except PyMongoError:
        return _err(ErrorCode.ERR_INTERNAL.value, "db error")
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

def logout(session_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        if session_id and isinstance(session_id, str) and session_id.strip():
            _revoke_session(session_id.strip())
        return _ok({"logged_out": True})
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

    

