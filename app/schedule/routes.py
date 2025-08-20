from __future__ import annotations

from flask import Blueprint, jsonify, request
from datetime import datetime, date
from app.utils.time import KST
from .service import open_week_slots, get_week_slots
from app.auth.service import jwt_required, role_required

bp = Blueprint("schedule", __name__)

def _parse_date_or_today(v: str | None) -> date:
    if not v:
        return datetime.now(tz=KST).date()
    return datetime.strptime(v, "%Y-%m-%d").date()

@bp.get("/week")
def week():
    start = request.args.get("start")
    d = _parse_date_or_today(start)
    data = get_week_slots(d)
    return jsonify({"ok": True, "base_date": d.isoformat(), 'days':data})

@bp.post("/open")
@jwt_required
@role_required(["admin"])
def open_week():
    start = request.args.get("start")
    d = _parse_date_or_today(start)
    result = open_week_slots(d)
    return jsonify({"ok": True, "base_date": d.isoformat(), **result}), 201