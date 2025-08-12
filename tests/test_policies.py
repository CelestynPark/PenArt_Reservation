from datetime import datetime, timedelta
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.policies.rules import (
    is_within_24h,
    can_change_or_cancel,
    require_consecutive_slots,
)

def test_is_within_24h_true():
    now = datetime(2025, 8, 10, 12, 0, 0)
    start = now + timedelta(hours=23, minutes=59)
    assert is_within_24h(start, now) is True

def test_is_within_24h_false():
    now = datetime(2025, 8, 10, 12, 0, 0)
    start = now + timedelta(hours=24, minutes=0)
    assert is_within_24h(start, now) is False

def test_can_change_or_cancel_before_24h():
    now = datetime(2025, 8, 10, 12, 0, 0)
    start = now + timedelta(hours=26)
    ok, use_token, msg = can_change_or_cancel(start, now, adjust_tokens=0)
    assert ok is True and use_token is False
    assert "자유" in msg

def test_can_change_or_cancel_within_24h_with_token():
    now = datetime(2025, 8, 10, 12, 0, 0)
    start = now + timedelta(hours=2)
    ok, use_token, msg = can_change_or_cancel(start, now, adjust_tokens=1)
    assert ok is True and use_token is True
    assert "조율권" in msg

def test_can_change_or_cancel_within_24h_no_token():
    now = datetime(2025, 8, 10, 12, 0, 0)
    start = now + timedelta(hours=2)
    ok, use_token, msg = can_change_or_cancel(start, now, adjust_tokens=0)
    assert ok is False and use_token is False
    assert "불가" in msg

def test_require_consecutive_slots_true():
    slots = ["10:00", "12:00", "11:00"]
    assert require_consecutive_slots(slots, need=2) is True

def test_require_consecutive_slots_false():
    slots = ["10:00", "12:00", "14:00"]
    assert require_consecutive_slots(slots, need=2) is False

def test_require_consecutive_slots_need3_true():
    slots = ["10:00", "11:00", "12:00", "15:00"]
    assert require_consecutive_slots(slots, need=3) is True

def test_require_consecutive_slots_need3_false():
    slots = ["10:00", "11:00", "13:00"]
    assert require_consecutive_slots(slots, need=3) is False

