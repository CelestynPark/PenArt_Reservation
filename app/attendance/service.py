from __future__ import annotations

from datetime import datetime, timedelta
from typing import Tuple, Dict, List
from bson import ObjectId
from flask import current_app
from app.db import get_db
from app.utils.time import KST

def _first_slot(db, slot_ids: List[ObjectId]) -> dict | None:
    cur = db.slots.find({"_id": {"$in": slot_ids}}).sort([("date", 1), ("start", 1)])
    return cur.next() if cur else None
    
def _to_kst_datetime(day: str, hm: str) -> datetime:
    return KST.localize(datetime.strptime(f"{day} {hm}", "%Y-%m-%d %H:%M"))

def admin_confirm_attendance(reservation_id: str) -> Tuple[bool, str | dict]:
    db = get_db()
    resv = db.reservations.find_one({"_id": ObjectId(reservation_id)})
    if not resv or resv.get("status") != "BOOKED":
        return False, "출석 확정할 예약이 없거나 상태가 올바르지 않습니다."
    
    first_slot = _first_slot(db, resv["slot_ids"])
    if not first_slot:
        return False, "슬롯 정보를 찾을 수 없습니다."
    
    if datetime.now(tz=KST) < _to_kst_datetime(first_slot["date"], first_slot["start"]):
        return False, "수업 시작 이전에는 출석 확정을 할 수 없습니다."
    
    db.reservations.update_one({"_id": resv["_id"]}, {"$set": {"status": "ATTENDED"}})
    return True, {"reservation_id": str(resv["_id"]), "status": "ATTENDED"}

def admin_mark_no_show(reservation_id: str) -> Tuple[bool, str | dict]:
    db = get_db()
    resv = db.reservations.find_one({"_id": ObjectId(reservation_id)})
    if not resv or resv.get("status") != "BOOKED":
        return False, "노쇼 처리할 예약이 없거나 상태가 올바르지 않습니다."
    
    first_slot = _first_slot(db, resv["slot_ids"])
    if not first_slot:
        return False, "슬롯 정보를 찾을 수 없습니다."
    
    start_dt = _to_kst_datetime(first_slot["date"], first_slot["start"])
    if datetime.now(tz=KST) < start_dt + timedelta(minutes=10):
        return False, "수업 시작 10분 이후로부터 노쇼 처리할 수 있습니다."
    
    db.reservations.update_one({"_id": resv["_id"]}, {"$set": {"status": "NO_SHOW"}})
    return True, {"reservation_id": str(resv["_id"]), "status": "NO_SHOW"}

def sweep_no_show(grace_minutes: int = 10) -> Dict[str, int]:
    db = get_db()
    now = datetime.now(tz=KST)
    threshold = now - timedelta(minutes=grace_minutes)

    count_scanner = 0
    count_updated = 0

    for resv in db.reservations.find({"status": "BOOKED"}, projection={"slot_ids": 1}):
        count_scanner += 1
        first = _first_slot(db, resv["slot_ids"])
        if not first:
            continue
        start_db = _to_kst_datetime(first['date'], first['start'])
        if start_db <= threshold:
            r = db.reservations.update_one(
                {"_id": resv["_id"], "status": "BOOKED"},
                {"$set": {"status": "NO_SHOW"}}
            )
            if r.modified_count == 1:
                count_updated += 1

        return {"scanned": count_scanner, "updated": count_updated}