from flask import Blueprint, jsonify
from app.auth.service import jwt_required, current_user_id
from .service import confirm_attendance, mark_no_show

bp = Blueprint("attendance", __name__)

@bp.post("/<resv_id>/confirm")
@jwt_required
def confirm(resv_id: str):
    uid = current_user_id()
    ok, payload = confirm_attendance(uid, resv_id)
    if not ok:
        return jsonify({"ok": False, "error": payload}), 400
    return jsonify({"ok": True, "result": payload})

@bp.post("/<resv_id>/noshow")
@jwt_required
def noshow(resv_id: str):
    uid = current_user_id()
    ok, payload = mark_no_show(uid, resv_id)
    if not ok:
        return jsonify({"ok": False, "error": payload}), 400
    return jsonify({"ok": True, "result": payload})