from __future__ import annotations

from typing import Dict, List
from datetime import datetime, date
from pymongo.errors import DuplicateKeyError

from flask import current_app
from app.utils.time import week_dates_for_open, generate_hour_slots, ymd, hm, KST

def open_week_slots(base_date: date) -> Dict[str, int]:
    db = current_app.config["MONGO_DB_HANDLE"]
    inserted, skipped = 0, 0

    for d in week_dates_for_open(base_date):
        for start, end, _ in generate_hour_slots():
            doc = {
                "date": ymd(d),
                "weekday": d.weekday(),
                "start": hm(start),
                "end": hm(end),
                "is_lunch": False,
                "is_open": True,
                "capacity": 1,
                "created_at": datetime.now(tz=KST)
            }
            try:
                db.slots.insert_one(doc)
                inserted += 1
            except DuplicateKeyError:
                skipped += 1
    return {"inserted": inserted, "skipped": skipped}

def get_week_slots(base_date: date) -> Dict[str, int[dict]]:
    db = current_app.config["MONGO_DB_HANDLE"]
    days = week_dates_for_open(base_date)
    result: Dict[str, int[dict]] = {ymd(d): [] for d in days}

    cursor = db.slots.find(
        {"date": {"$in": list(result.keys())}},
            sort=[("date", 1), ("start", 1)]
    )
    for doc in cursor:
        day = doc["date"]
        result[day].append(
            {
                "_id": str(doc["_id"]),
                "date": doc["date"],
                "weekday": doc["weekday"],
                "start": doc["start"],
                "end": doc["end"],
                "is_open": doc.get("is_open", True),
                "capacity": doc.get("capacity", 1)
            }
        )
    return result