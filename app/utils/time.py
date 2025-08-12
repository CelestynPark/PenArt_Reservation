from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import List, Tuple
import pytz

KST = pytz.timezone("Asia/Seoul")

MON, TUE, WED, THU, FRI, SAT, SUN = 0, 1, 2, 3, 4, 5, 6

def now_kst() -> datetime:
    return datetime.now(tz=KST)

def to_kst(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return KST.localize(dt)
    return dt.astimezone(KST)

def monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())

def week_dates_for_open(d: date) -> List[date]:
    mon = monday_of_week(d)
    return [mon + timedelta(days=THU), mon + timedelta(days=FRI), mon + timedelta(days=SAT)]

def generate_hour_slots() -> List[Tuple[time, time, bool]]:
    slots: List[Tuple[time, time, bool]] = []
    for h in range(10, 19):
        start = time(hour=h, minute=0)
        end = (datetime.combine(date.today(), start) + timedelta(hours=1)).time()
        is_lunch = (h == 13)
        if is_lunch:
            continue
        slots.append((start, end, False))
    return slots

def ymd(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def hm(t: time) -> str:
    return t.strftime("%H:%M")