from datetime import datetime, timedelta
from typing import Iterable, List, Tuple

def is_within_24h(start_dt: datetime, now: datetime) -> bool:
    return start_dt - now < timedelta(hours=24)

def can_change_or_cancel(
        start_dt: datetime,
        now: datetime,
        adjust_tokens: int
) -> Tuple[bool, bool, str]:
    if not is_within_24h(start_dt, now):
        return True, False, "24시간 이전: 자유 변경/취소 가능"
    
    if adjust_tokens > 0:
        return True, True, "24시간 이내, 조율권 사용 시 1회 허용"
    
    return False, False, "24시간 이내: 조율권 없음으로 불가"

def require_consecutive_slots(slot_time: Iterable[str], need: int = 2):
    def to_minutes(hhmm: str) -> int:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    
    minutes = sorted(to_minutes(s) for s in set(slot_time))
    if len(minutes) < need:
        return False
    
    streak = 1
    for i in range(1, len(minutes)):
        if minutes[i] - minutes[i - 1] == 60:
            streak += 1
            if streak >= need:
                return True
        else:
            streak = 1
    return False

