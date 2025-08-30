from __future__ import annotations
"""
정책/규칙 모듈
- 24시간 규칙 + 조율권
- 심화(ADVANCED) 2슬롯 연속성 검증
- 중복 예약(동일 시간대) 방지 헬퍼
"""

from typing import Any, Dict, List, Tuple
import datetime as dt

# 코스 상수
COURSE_BEGINNER = "BEGINNER"         # 60분 x 8
COURSE_INTERMEDIATE = "INTERMEDIATE" # 60분 x 4
COURSE_ADVANCED = "ADVANCED"         # 120분 x 4 (연속 2슬롯)

COURSE_MINUTES = {
    COURSE_BEGINNER: 60,
    COURSE_INTERMEDIATE: 60,
    COURSE_ADVANCED: 120
}

# --------------------------
# 24시간 규칙 + 조율권
# --------------------------
def within_24h_or_token(
        start_dt: dt.datetime,
        adjust_tokens: int,
        use_adjust_token: bool | None = None,
        now: dt.datetime | None= None
) -> Tuple[bool, bool, str]:
    """
    24시간 규칙 + 조율권 사용 가능성 판단.
    - 24시간 이전: 조율권 필요 없음 -> 허용
    - 24시간 이후: 조율권 있으면 허용(사용), 없으면 거부
    반환: (allow, will_use_token, reason)
    """
    now = now or dt.datetime.now(tz=start_dt.tzinfo)
    delta = start_dt - now

    # 24시간 이전이면 자유 번경/취소 허용
    if delta.total_seconds() >= 24 * 60 * 60:
        return True, False, "24시간 이전이면 조율권 없이 허용됩니다."
    
    # 24시간 이내
    if adjust_tokens > 0:
        # 클라이언트 체크박스와 무관하게 서버에서 자동 사용을 허용할 수도 있음
        will_use = True if use_adjust_token is None else bool(use_adjust_token)
        if not will_use:
            return False, False, "24시간 이내에는 조율권 사용 동의가 필요합니다."
        return True, True, "24시간 이내이나 조율권 사용으로 허용됩니다"
    
    return False, False, "24시간 이내이며 조율권이 없습니다."

def within_24h(start_dt: dt.datetime, now: dt.datetime | None = None) -> bool:
    """
    호환 헬퍼: 수업 시작이 24시간 '이내'인지 여부만 반환.
    - 일부 라우터에서 단순 불리언을 기대하는 경우를 위해 제공.
    """
    now = now or dt.datetime.now(tz=start_dt.tzinfo)
    return (start_dt - now).total_seconds() < 24 * 60 * 60