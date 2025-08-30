from __future__ import annotations

from flask import Blueprint, jsonify, request
from bson import ObjectId

from app.auth.service import jwt_required, current_user_id, role_required
from app.db import get_db
from app.utils.phone import normalize_phone
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
        slot_docs = list(db.slots.find({"_id": {"$in": d["slot_ids"]}}))
        slot_docs.sort(key=lambda s: (s["date"], s["start"]))
        slot_detail = [
            {
                "id": str(s["_id"]),
                "date": s["date"],
                "start": s["start"],
                "end": s["end"]
            }
            for s in slot_docs
        ]

        items.append(
            {
                "_id": str(d["_id"]),
                "enrollment_id": str(d["enrollment_id"]),
                "slot_ids": [str(x) for x in d["slot_ids"]],
                "slot_details": slot_detail,
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

@bp.post("/admin/enrollments")
@jwt_required
@role_required(["admin"])
def admin_create_enrollment():
    db = get_db()
    data = request.get_json(force=True, silent=True) or {}

    user = None
    if data.get("user_id"):
        try:
            user = db.users.find_one({"_id": ObjectId(data["user_id"])})
        except Exception as e:
            return jsonify({"ok": False, "error": "user_id 형식이 올바르지 않습니다."}), 400
        
    elif data.get("phone"):
        phone_norm = normalize_phone(data["phone"])
        if not phone_norm:
            return jsonify({"ok": False, "error": "전화번호가 유효하지 않습니다."}), 400
        user = db.users.find_one({"phone": phone_norm})
    else:
        return jsonify({"ok": False, "error": "user_id 또는 phone이 필요합니다."}), 400
    
    if not user:
        return jsonify({"ok": False, "error": "사용자를 찾을 수 없습니다."}), 404
    
    course_type = (data.get("course_type") or "").upper()
    if course_type not in ["BASIC", "INTERMEDIATE", "ADVANCED"]:
        return jsonify({"ok": False, "error": "course_type이 올바르지 않습니다."}), 400
    
    if course_type == "BEGINNER":
        session_minutes, total_sessions = 60, 8
    elif course_type == "INTERMEDIATE":
        session_minutes, total_sessions = 60, 4
    else:
        session_minutes, total_sessions = 120, 4

    doc = {
        "user_id": user["_id"],
        "course_type": course_type,
        "session_minutes": session_minutes,
        "total_sessions": total_sessions,
        "remaining_sessions": total_sessions,
        "adjust_tokens": 1,
        "status": "ACTIVE"
    }
    ins = db.enrollments.insert_one(doc)
    return jsonify({"ok": True, "enrollment_id": str(ins.inserted_id)})
    