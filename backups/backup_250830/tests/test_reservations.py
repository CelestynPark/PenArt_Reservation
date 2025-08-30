from app.reservations.service import COURSE

def test_course_consts():
    assert COURSE["BEGINNER"]["need_slots"] == 1
    assert COURSE["ADVANCED"]["need_slots"] == 2
    