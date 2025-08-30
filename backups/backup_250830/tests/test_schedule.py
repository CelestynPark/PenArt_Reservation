from datetime import date, time
from app.utils.time import week_dates_for_open, generate_hour_slots, ymd, hm, THU, FRI, SAT

def test_week_dates_for_open_includes_thu_fri_sat():
    base = date(2025, 8, 4)
    days = week_dates_for_open(base)
    assert len(days) == 3
    assert [d.weekday() for d in days] == [THU, FRI, SAT]

def test_generate_hour_slots_excludes_lunch():
    slots = generate_hour_slots()
    assert len(slots) == 8
    
    for s, e, is_lunch in slots:
        assert isinstance(s, time) and isinstance(e, time)
        assert is_lunch is False
    assert hm(slots[0][0]) == "10:00"

def test_ymd_hm_format_helper():
    d = date(2025, 8, 7)
    assert ymd(d) == "2025-08-07"
    