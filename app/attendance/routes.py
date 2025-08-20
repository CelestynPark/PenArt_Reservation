from __future__ import annotations
from flask import Blueprint, jsonify
from app.auth.service import jwt_required, role_required
from .service import admin_confirm_attendance, admin_mark_no_show

bp = Blueprint("attendance", __name__)

@bp.post("/<resv_id>/confirm")
@jwt_required
def confirm(resv_id: str):
    ok, payload = admin_confirm_attendance(resv_id)
    if not ok:
        return jsonify({"ok": False, "error": payload}), 400
    return jsonify({"ok": True, "result": payload})

@bp.post("/<resv_id>/noshow")
@jwt_required
def noshow(resv_id: str):
    ok, payload = admin_mark_no_show(resv_id)
    if not ok:
        return jsonify({"ok": False, "error": payload}), 400
    return jsonify({"ok": True, "result": payload})