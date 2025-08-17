from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional, Tuple

import jwt
from flask import current_app, request, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash
from bson import ObjectId

from app.db import get_db
from app.utils.phone import normalize_phone

def _jwt_secret() -> str:
    return current_app.config["SECRET_KEY"]

def create_user(name: str, phone_raw: str, email: Optional[str], password: str) -> Tuple[bool, str]:
    db = get_db()
    phone = normalize_phone(phone_raw)
    if not phone:
        return False, "유효하지 않은 전화번호입니다."
    
    exists = db.users.find_one({"phone": phone})
    if exists:
        return False, "이미 등록된 전화번호입니다."
    
    doc = {
        "name": name,
        "phone": phone,
        "email": email,
        "password_hash": generate_password_hash(password),
        "created_at": datetime.now(timezone.utc),
    }
    res = db.users.insert_one(doc)
    return True, str(res.inserted_id)

def authenticate(login: str, password: str) -> Tuple[bool, str]:
    db = get_db()

    phone = normalize_phone(login)
    if phone:
        user = db.users.find_one({"phone": phone})
    else:
        user = db.users.find_one({"email": login})

    if not user:
        return False, "존재하지 않는 사용자입니다."
    
    if not check_password_hash(user["password_hash"], password):
        return False, "비밀번호가 올바르지 않습니다."
    
    payload = {
        "sub": str(user["_id"]),
        "name": user["name"],
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=12),
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm="HS256")
    return True, token

def jwt_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"ok": False, "error": "인증 토큰이 필요합니다."}), 401
        token = auth.split(" ", 1)[1].strip()
        try:
            decoded = jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"ok": False, "error": "토큰이 만료되었습니다."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"ok": False, "error": "유효하지 않은 토큰입니다."}), 401

        g.user_id = decoded.get("sub")
        g.user_name = decoded.get("name")
        if not g.user_id:
            return jsonify({"ok": False, "error": "토큰에 사용자 정보가 없습니다."}), 401
        return fn(*args, **kwargs)
    return wrapper

def current_user_id() -> Optional[ObjectId]:
    try:
        return ObjectId(g.user_id)
    except Exception:
        return None