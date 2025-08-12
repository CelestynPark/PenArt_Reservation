from __future__ import annotations

from flask import Blueprint, jsonify, request
from .service import create_user, authenticate

bp = Blueprint("auth", __name__)

@bp.route("/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True, silent=True) or {}
    ok, info = create_user(
        name=data.get("name").strip(),
        phone_raw=data.get("phone", "").strip(),
        email=(data.get("email") or "").strip() or None,
        password=data.get("password", ""),
    )
    if not ok:
        return jsonify({"ok": False, "error": info}), 400
    return jsonify({"ok": True, "user_id": info}), 201

@bp.post("/login")
def login():
    data = request.get_json(force=True, silent=True) or {}
    ok, token_or_msg = authenticate(
        login=data.get("login", "").strip(),
        password=data.get("password", ""),
    )
    if not ok:
        return jsonify({"ok": False, "error": token_or_msg}), 401
    return jsonify({"ok": True, "token": token_or_msg})
