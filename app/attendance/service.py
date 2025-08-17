from __future__ import annotations

from datetime import datetime
from typing import Tuple, Dict, List
from bson import ObjectId
from flask import current_app
from app.db import get_db
from app.utils.time import KST

def _earliest_slot(db, slot_ids: List[ObjectId]) -> dict | None:
    docs = list(db.slots.find({"_id": {"$in": slot_ids}}))
    if not docs:
        return None
    docs.sort(key=lambda d: (d["date"], d["start"]))
    return docs[0]

def confirm_attendance(user_id: ObjectId, reservation_id: str) -> Tuple[bool, str | dict]:
    db = get_db()
    resv = db.reservations.find_one({"_id": ObjectId(reservation_id), "user_id": user_id})
    if not resv or resv.get("status") != "BOOKED":
        return False, "출석 확정할 예약이 없거나 상태가 올바르지 않습니다."
    
    first_slot = _earliest_slot(db, resv["slot_ids"])
    if not first_slot:
        return False, "슬롯 정보를 찾을 수 없습니다."
    
    start_dt = datetime.strptime(f"{first_slot['date']}{first_slot['start']}", "%Y-%m-%d %H:%M")
    start_dt = KST.localize(start_dt)
    now = datetime.now(tz=KST)
    if now < start_dt:
        return False, "수업 시작 이전에는 출석 확정을 할 수 없습니다."
    
    db.reservations.update_one({"_id": resv["_id"]}, {"$set": {"status": "ATTENDED"}})
    return True, {"reservation_id": str(resv["_id"]), "status": "ATTENDED"}

def mark_no_show(user_id: ObjectId, reservation_id: str) -> Tuple[bool, str | dict]:
    db = get_db()
    resv = db.reservations.find_one({"_id": ObjectId(reservation_id), "user_id": user_id})
    if not resv or resv.get("status") != "BOOKED":
        return False, "노쇼 처리할 예약이 없거나 상태가 올바르지 않습니다."
    
    first_slot = _earliest_slot(db, resv["slot_ids"])
    if not first_slot:
        return False, "슬롯 정보를 찾을 수 없습니다."
    
    start_dt = datetime.strptime(f"{first_slot['date']} {first_slot['start']}", "%Y-%m-%d %H:%M")
    start_dt = KST.localize(start_dt)
    now = datetime.now(tz=KST)

    if now < (start_dt.replace(tzinfo=KST) + (now - now)):
        pass
    if now < start_dt:
        return False, "수업 시작 노쇼 처리할 수 없습니다."
    
    db.reservations.update_one({"_id": resv["_id"]}, {"$set": {"status": "NO_SHOW"}})
    return True, {"reservation_id": str(resv["_id"]), "status": "NO_SHOW"}