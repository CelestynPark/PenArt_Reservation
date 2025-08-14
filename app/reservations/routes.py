from __future__ import annotations

from flask import Blueprint, jsonify, request
from bson import ObjectId

from app.auth.service import jwt_required, current_user_id
from app.db import get_db
from .service import create_reservation, change_reservation, cancel_reservation

bp = Blueprint("reservation", __name__)

@bp.post("")
@jwt_required
def create_resv():
    user_id = current_user_id()
    data = request.get_json(force=True, silent=True) or {}
    ok, payload = create_reservation(
        user_id=user_id,
        enrollment_id=data.get("enrollment_id", ""),
        date_str=data.get("date", ""),
        start_str=data.get("start", "")
    )
    if not ok:
        return jsonify({"ok": False, "error": payload}), 400
    return jsonify({"ok": True, "reservation": payload}), 201

@bp.patch("/<resv_id>")
@jwt_required
def change_resv(resv_id: str):
    user_id = current_user_id()
    data = request.get_json(force=True, silent=True) or {}
    ok, payload = change_reservation(
        user_id=user_id,
        reservation_id = resv_id,
        date_str=data.get("date", ""),
        start_str=data.get("start", ""),
        ues_adjsut_token=bool(data.get("use_adjust_token", False))
    )
    if not ok:
        return jsonify({"ok": False, "error": payload}), 400
    return jsonify({"ok": True, "reservation": payload}), 201
    
@bp.delete("/<resv_id>")
@jwt_required
def cancel_resv(resv_id: str):
    user_id = current_user_id()
    use_adjust = request.args.get("use_adjust_token", "false").lower() == "true"
    ok, payload = cancel_reservation(
        user_id=user_id, reservation_id = resv_id, use_adjust_token=use_adjust
    )
    if not ok:
        return jsonify({"ok": False, "error": payload}), 400
    return jsonify({"ok": True, "reservation": payload}), 201

@bp.get("/me")
@jwt_required
def my_reservations():
    db = get_db()
    user_id = current_user_id()
    cursor = db.reservations.find({"user_id": user_id}).sort("created_at", -1)
    items = []
    for d in cursor:
        items.append(
            {
                "_id": str(d["_id"]),
                "enrollment_id": str(d["enrollment_id"]),
                "slot_ids": [str(x) for x in d["slot_ids"]],
                "status": d["status"],
                "used_adjust_token": d.get("user_adjust_token", False)
            }
        )
    return jsonify({"ok": True, "items": items})

@bp.get("/me/enrollments")
@jwt_required
def my_enrollments():
    db = get_db()
    user_id = current_user_id()
    cursor = db.enrollments.find({"user_id": user_id})
    items = []
    for e in cursor:
        items.append(
            {
                "_id": str(e["_id"]),
                "course_type": e["course_type"],
                "remaining_sessions": e.get("remaining_sessions", 0),
                "adjust_tokens": e.get("adjust_tokens", 0),
                "status": e.get("status", "ACTIVE")
            }
        )
    return jsonify({"ok": True, "items": items})

