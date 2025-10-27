from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.repositories import availability as availability_repo
from app.services import availability_service as avail_svc
from app.extensions import get_mongo
from app.utils.time import parse_kst_date, to_utc, isoformat_utc


def _iso_kst(date_kst: str, hhmm: str) -> str:
    start_utc, _ = parse_kst_date(date_kst)
    kst_midnight = (start_utc + timedelta(hours=9)).replace(hour=0, minute=0, second=0, microsecond=0)
    h, m = map(int, hhmm.split(":"))
    kst_dt = kst_midnight(hour=h, minute=m)
    return isoformat_utc(to_utc(kst_dt))


def _minutes_between(iso_start: str, iso_end: str) -> int:
    s = datetime.fromisoformat(iso_start.replace("Z", "+00:00"))
    e = datetime.fromisoformat(iso_end.replace("Z", "+00:00"))
    return int((e - s).total_seconds() // 60)


@pytest.fixture(autouse=True)
def _reset_availability(db):
    pass


def test_base_days_applies_next_monday_kst(client, freeze_time):
    """
    base_days 변경이 KST 기준 '다음 주 월요일 00:00' 이후의 날짜부터 적용되는지 검증.
    내부 compose_rules_for_date_kst의 base_days_applied 플래그로 경계 확인.
    """
    # 초기 규칙: 월 09-12 (60분 슬롯)
    availability_repo.save_rules(
        [{"dow": [1], "start": "09:00", "end": "12:00", "slot_min": 60}]
    )

    # 기준 시각: 2025-01-10(금) 09:00 KST
    with freeze_time("2025-01-10T09:00:00+09:00"):
        # base_days를 월~금에서 화~목으로 변경 (updated_at가 이 시각으로 기록됨)
        availability_repo.set_base_days([2, 3, 4])

        # 경계 전 날짜들 (이번 주 주말/다음주 월 이전)은 base_days_applied=False 이어야 함
        comp_fri = avail_svc.compose_rules_for_date_kst("2025-01-10") # 금
        comp_sat = avail_svc.compose_rules_for_date_kst("2025-01-11") # 토
        comp_sun = avail_svc.compose_rules_for_date_kst("2025-01-12") # 일
        assert comp_fri["ok"] and comp_sat["ok"] and comp_sun["ok"]
        assert comp_fri["data"]["base_days_applied"] is False
        assert comp_sat["data"]["base_days_applied"] is False
        assert comp_sun["data"]["base_days_applied"] is False

        # 경계 당일(다음 주 월요일)부터는 True
        comp_mon = avail_svc.compose_rules_for_date_kst("2025-01-13") # 다음 주 월
        assert comp_mon["ok"]
        assert comp_mon["data"]["base_days_applied"] is True

    # 응답 포맷 검증(엔드포인트): 경계 전/후 모두 envelope 형식
    with freeze_time("2025-01-11T09:00:00+09:00"):
        r1 = client.get("/api/availability?date=2025-01-11")
        assert r1.status_code == 200
        body1 = r1.get_json()
        assert isinstance(body1, dict) and "ok" in body1 and "data" in body1

    with freeze_time("2025-01-13T09:00:00+09:00"):
        r2 = client.get("/api/availability?date=2025-01-13")
        assert r2.status_code == 200
        body2 = r2.get_json()
        assert isinstance(body2, dict) and "ok" in body2 and "data" in body2

    
def test_existing_bookings_unchanged(client, freeze_time, db):
    """
    base_days 변경이 기존 예약에 영향을 주지 않음을 검증.
    - 변경 전 생성된 예약은 그대로 유지되고,
    - 가용 슬롯 계산 시에도 해당 슬롯은 계속 충돌로 제외된다.
    """
    # 월 09-12, 60분 슬롯
    availability_repo.save_rules(
        [{"dow": [1], "start": "09:00", "end": "12:00", "slot_min": 60}]
    )
    date_kst = "2025-01-13" # 월(다음 주 월요일부터 적용)

    # 변경 전 시점에서 예약 09:00~10:00을 생성해 둔다.
    mongo = get_mongo()
    bookings = mongo.get_database().get_collection("bookings")
    bk_start = _iso_kst(date_kst, "09:00")
    bk_end = _iso_kst(date_kst, "10:00")
    bookings.insert_one(
        {
            "service_id": "svc1",
            "start_at": datetime.fromisoformat(bk_start.replace("Z", "+00:00")),
            "end_at": datetime.fromisoformat(bk_end.replace("Z", "+00:00")),
            "status": "confirmed",
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "code": "BKG-UNCHANGED",
            "customer_id": "cust1",
            "source": "web",
            "history": [],
        }
    )

    # base_days 변경(금요일) → 다음 주 월 00:00부터 적용
    with freeze_time("2025-01-10T09:00:00+09:00"):
        availability_repo.set_base_days([2, 3, 4])  # 화~목

    # 경계 이후(월요일) 가용 조회: 09:00 슬롯은 예약 충돌로 제외이어야 한다
    with freeze_time("2025-01-13T08:00:00+09:00"):
        r = client.get(f"/api/availability?date={date_kst}")
    assert r.status_code == 200
    slots = r.get_json()["data"]["slots"]
    # 09:00~10:00은 빠지고, 다음 후보 10:00~11:00 / 11:00~12:00만 가능
    for s in slots:
        assert s["start_at"] != bk_start
    # 슬랏들이 존재하더라도 기존 예약 슬롯은 반환되지 않음
    # (명시적 검증: 10:00 슬롯은 존재할 수 있다)
    assert all(_minutes_between(s["start_at"], s["end_at"]) in (60, 30) for s in slots)


def test_slots_before_rollover_unchanged_after_rollover_changed(client, freeze_time):
    """
    경계 전 주의 동일 요일 슬롯과 경계 다음 주 요일 슬롯의 비교.
    - 규칙이 명시된 요일은 base_days 제외에도 계속 가용(명시 규칙이 우선)
    - 규칙이 없는 요일은 base_days 적용 이후 기본 비가용 처리
    """
    # 규칙: 월 09-12 (60분), 화/수/목/금은 규칙 없음
    availability_repo.save_rules(
        [{"dow": [1], "start": "09:00", "end": "12:00", "slot_min": 60}]
    )

    # 1) 변경 전 주(경계 직전 주말에 변경 예정)
    before_mon = "2025-01-06" # 경계 전 월요일
    with freeze_time("2025-01-05T09:00:00+09:00"):
        r_before = client.get(f"/api/availability?date={before_mon}")
    assert r_before.status_code == 200
    slots_before = r_before.get_json()["data"]["slots"]
    assert len(slots_before) >= 2 # 09-10, 10-11, 11-12 중 과거/현재 시각에 따라 2~3개

    # 2) 금요일에 base_days를 화~목으로 변경 → 다음 주 월요일부터 적용
    with freeze_time("2025-01-10T09:00:00+09:00"):
        availability_repo.set_base_days([2, 3, 4])  # 화~목

    # 3) 경계 다음 주의 월요일: 월 규칙이 존재하므로 여전히 슬롯이 나와야 함(명시 규칙 우선)
    after_mon = "2025-01-13"
    with freeze_time("2025-01-12T09:00:00+09:00"):
        r_after = client.get(f"/api/availability?date={after_mon}")
    assert r_after.status_code == 200
    slots_after = r_after.get_json()["data"]["slots"]
    assert len(slots_after) > 0

    # 4) 경계 다음 주의 금요일: 규칙 없음 + base_days(화~목)에 포함되지 않아 기본 비가용
    after_fri = "2025-01-17"
    with freeze_time("2025-01-12T09:00:00+09:00"):
        r_after_fri = client.get(f"/api/availability?data={after_fri}")
    assert r_after_fri.status_code == 200
    assert r_after_fri.get_json()["data"]["slots"] == []

    # 응답 포맷(일관성) 확인
    for body in (r_before.get_json(), r_after.get_json(), r_after_fri.get_json()):
        assert isinstance(body, dict)
        assert "ok" in body and "data" in body and isinstance(body["data"], dict)
        assert "date_kst" in body["data"] and "slots" in body["data"]
        