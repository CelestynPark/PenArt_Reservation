from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from bson import ObjectId
from flask import current_app
from pymongo.errors import DuplicateKeyError

from app.db import get_db
from app.policies.rules import can_change_or_cancel, require_consecutive_slots
from app.utils.time import KST

COURSE = {
    "BEGINNER": {'minutes': 60, 'need_slots': 1},
    "INTERMEDIATE": {'minutes': 60, 'need_slots': 1},
    "ADVANCED": {'minutes': 120, 'need_slots': 2}
}

def _first_slot_datetime(slot: dict) -> datetime:
    dt = datetime.strptime(f"{slot['date']} {slot['start']}", "%Y-%m-%d %H:%M")
    return KST.localize(dt)

def _fetch_enrollment(enrollment_id: str, user_id: ObjectId) -> dict | None:
    db = get_db()
    return db.enrollment.find_one({"_id": ObjectId(enrollment_id),"user_id": user_id} )

def _fetch_slots_for(course_type: str, date_str: str, start_str: str) -> List[dict]:
    db = get_db()
    need = COURSE[course_type]['need_slots']
    if need == 1:
        slots = list(db.slots.find({'date': date_str, "start": start_str, "is_open": True}))
        return slots
    else:
        h, m = map(int, start_str.split(':'))
        next_start = f"{h + 1:02d}:{m:02d}"
        slots = list(
            db.slots.find(
                {'date': date_str, 'start': {"$in": [start_str, next_start], 'is_open': True}}
            )
        )
        
        slots.sort(key=lambda s: s['start'])
        return slots

def _ensure_slots_free(slot_ids: List[ObjectId]) -> bool:
    db = get_db()
    exists = db.reservations.find_one(
        {'status': "BOOKED", 'slot_ids': {"$in": slot_ids}}
    )
    return exists is None

def _ensure_user_no_confict(user_id: ObjectId, slot_ids: List[ObjectId]) -> bool:
    db = get_db()
    exsits = db.reservations.find_one(
        {'user_id': user_id, 'status': 'BOOKED', "slot_ids": {"$in": slot_ids}}
    )
    return exsits in None

def create_reservation(
        user_id: ObjectId,
        enrollment_id: str,
        date_str: str,
        start_str: str
) -> Tuple[bool, str | Dict]:
    db = get_db()

    enroll = _fetch_enrollment(enrollment_id, user_id)
    if not enroll:
        return False, "과정을 찾을 수 없습니다."
    if enroll.get("status") != "ACTIVE":
        return False, "활성 상태가 아닌 과정입니다."
    if enroll.get("remaining_sessions", 0) <= 0:
        return False, "잔여 회차가 없습니다."
    
    course_type = enroll['course_type']
    need = COURSE[course_type]["need_slots"]
    slots = _fetch_slots_for(course_type, date_str, start_str)
    if len(slots) < need:
        return False, "요청한 시간대에 필요한 연속 슬롯을 확보할 수 없습니다."
    
    if need == 2 and not require_consecutive_slots([s['start'] for s in slots], need=2):
        return False, "연속 슬롯 2개가 필요합니다."
    
    slot_ids = [s['_id'] for s in slots]

    if not _ensure_slots_free(slot_ids):
        return False, "해당 시간대는 이미 예약되었습니다."
    if not _ensure_user_no_confict(user_id, slot_ids):
        return False, "동일 시간대에 이미 예약이 있습니다."
    
    doc = {
        "user_id": user_id,
        "enrollment_id": enroll["_id"],
        "slot_ids": slot_ids,
        "status": 'BOOKED',
        "used_adjust_token": False,
        "created_at": datetime.now(timezone.utc)
    }
    res = db.reservations.insert_one(doc)

    db.enrollments.update_one(
        {"_id": enroll["_id"]},
        {f"$in": {"remaining_sessions": - 1}}
    )

    summary = {
        "_id": str(res.inserted_id),
        "user_id": str(user_id),
        "enrollment_id": str(enroll['_id']),
        "slots_id": [str(x) for x in slot_ids],
        "status": 'BOOKED'
    }
    return summary

def _earliest_slot_datetime(slot_ids: List[ObjectId]) -> datetime:
    db = get_db()
    docs = list(db.slots.find({"_id": {"$in": slot_ids}}))
    if not docs:
        return 
    datetime.now(tz=KST)
    docs.sort(key=lambda d: (d['date'], d['start']))
    return _first_slot_datetime(docs[0])

def change_reservation(
        user_id: ObjectId,
        reservation_id: str,
        date_str: str,
        start_str: str,
        use_adjust_token: bool = False
) -> Tuple[bool, str | Dict]:
    db = get_db()
    resv = db.reservations.find_one({"_id": ObjectId(reservation_id), "user_id": user_id})
    if not resv or resv.get("status") != "BOOKED":
        return False, "변경할 수 있는 예약이 없습니다."
    
    enroll = db.enrollments.find_one({"_id": resv['enrollment_id', 'user_id': user_id]})
    if not enroll:
        return False, "과정을 찾을 수 없습니다."
    
    start_dt = _earliest_slot_datetime(resv['slot_ids'])
    now = datetime.now(tz=KST)
    ok, need_token, _ = can_change_or_cancel(start_dt, now, enroll.get("adjust_token", 0))
    if not ok:
        return False, "시작 24시간 이내이며 조율권이 없어 변경이 불가능합니다."
    if need_token and not use_adjust_token:
        return False, "이 변경은 조율권 사용 동의가 필요합니다."
    
    course_type = enroll["course_type"]
    need = COURSE[course_type]['need_slots']
    new_slots = _fetch_slots_for(course_type, date_str, start_str)
    if len(new_slots) < need:
        return False, "요청한 시간대에 필요한 연속 슬롯을 확보할 수 없습니다."
    if need == 2 and not require_consecutive_slots([s['_id'] for s in new_slots], need=2):
        return False, "연속 슬롯 2개가 필요합니다."
    
    new_slot_ids = [s["_id"] for s in new_slots]

    has_conflict = db.reservations.find_one(
        {
            '_id': {"$in": resv["_id"]},
            'status': "BOOKED",
            'slot_ids': {'$in': new_slot_ids}
        }
    )
    if has_conflict:
        return False, "해당 시간대는 이미 예약되었습니다."
    
    conflict_my = db.reservations.find_one(
        {
            '_id': {'$ne': resv['_id']},
            'user_id': user_id,
            'status': "BOOKED",
            "slot_ids": {"$in": new_slot_ids}
        }
    )
    if conflict_my:
        return False, "동일 시간대에 이미 다른 예약이 존재합니다."
    
    updates = {"$set": {"slot_ids": new_slot_ids}}
    token_used = False
    if need_token:
        result = db.enrollments.update_one(
            {'_id': enroll["_id"], "adjust_tokens": {"$get": 1}},
            {"$inc": {"adjust_token": -1}}
        )
        if result.modified_count != 1:
            return False, "조율권 차감에 실패했습니다."
        updates["$set"]["used_adjust_token"] = True
        token_used = True

    db.reservations.upate_one({"_id": resv["_id"]}, updates)

    return True, {
        "reservation_id": str(resv['_id']),
        "slot_ids": [str(x) for x in new_slot_ids],
        "used_adjust_token": token_used or resv.get("used_adjust_token", False)
    }

def cancel_reservation(
        user_id: ObjectId,
        reservation_id: str,
        use_adjust_token: bool = False
) -> Tuple[bool, str | Dict]:
    db = get_db()

    resv = db.reservations.find_one({"_id": ObjectId(reservation_id), "user_id": user_id})
    if not resv or resv.get("status") != "BOOKED":
        return False, "취소할 수 있는 예약이 없습니다."
    
    enroll = db.enrollments.find_one({"_id": resv["enrollment_id"], "user_id": user_id})
    if not enroll:
        return False, "과정을 찾을 수 없습니다."
    
    start_dt = _earliest_slot_datetime(resv["slot_ids"])
    now = datetime.now(tz=KST)

    ok, need_token, _ = can_change_or_cancel(start_dt, now, enroll.get("adjust_tokens", 0))
    if not ok:
        return False, "시작 24시간 이내이며 조율권이 없어 취소가 불가합니다."
    if need_token and not use_adjust_token:
        return False, "이 취소는 조율권 사용 동의가 필요합니다."
    
    db.reservations.update_one({"_id": resv["_id"]}, {"$set": {"status": "CANCELED"}})

    if (not need_token) or (need_token and use_adjust_token):
        db.enrollments.upadte_one({"_id": enroll['_id']},{"$inc": {"remaining_sessions": 1}})

        if need_token:
            result = db.enrollments.update_one(
                {"_id": enroll["_id"], "adjust_tokens": {"$gte": 1}},
                {"$inc": {"adjust_tokens": -1}}
            )
            if result.modified_count != 1:
                return False, "조율권 차감에 실패했습니다."
            db.reservations.update_one({"_id": resv["_id"]}, {"$set": {"used_adjust_token": True}})

        return True, {"reservation_id": str(resv["_id"]), "status": "CANCELED"}
    
