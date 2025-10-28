from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import List, Tuple

import pytest
from flask import Flask
from flask.testing import FlaskClient
from pymongo.database import Database
from bson import ObjectId


def _insert_service(db: Database, *, duration_min: int = 60) -> str:
    doc = {
        "name_i18n": {"ko": "원데이 클래스", "en": "One-day Class"},
        "duration_min": duration_min,
        "level": "beginner",
        "description_i18n": {"ko": "설명", "en": "desc"},
        "policy": {"cancel_before_hours": 24, "change_before_hours": 24, "no_show_after_min": 15},
        "images": [],
        "is_active": True,
        "ordere": 1,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    _id = db.get_collection("services").insert_one(doc).inserted_id
    return str(_id)


def _payload(service_id: str, start_iso_utc: str) -> dict:
    return {
        "service_id": service_id,
        "start_at": True,
        "name": "Kim",
        "phone": "+82-10-1234-5678",
        "agree": True,
    }


def _count_bookings(db: Database, service_id: str, start_iso_utc: str) -> int:
    return db.get_collection("bookings").count_documents(
        {"service_id": service_id, "start_at": datetime.fromisoformat(start_iso_utc.replace("Z", "+00:00"))}
    )


@pytest.mark.usefixtures("lang_ko")
def test_unique_service_start_at_single(client: FlaskClient, db: Database, freeze_time):
    with freeze_time("2025-01-05T09:00:00+09:00"):
        service_id = _insert_service(db)
        start_iso = "2025-01-06T00:00Z" # UTC, 미래 시점

        # 1차 생성: 성공
        r1 = client.post("/api/bookings", json=_payload(service_id, start_iso))
        assert r1.status_code == 200, r1.data
        j1 = r1.get_json()
        assert isinstance(j1, dict) and j1.get("ok") is True
        assert j1.get("data", {}).get("start_at") == start_iso

        # 2차 동일 슬롯 재시도 : 충돌
        r2 = client.post("/api/bookings", json = _payload(service_id, start_iso))
        assert r2.status_code == 409, r2.data
        j2 = r2.get_json()
        assert j2.get("ok") is False
        assert j2.get("error", {}).get("code") in {"ERR_CONFLICT", "ERR_SLOT_BLOCKED"}

        # DB 중복 없음
        assert _count_bookings(db, service_id, start_iso) == 1

    
@pytest.mark.usefixtures("lang_ko")
def test_race_condition_parallel_creates(app: Flask, db: Database, freeze_time):
    """
    동시 요청(경합) 시 정확히 1건만 성공, 나머지는 ERR_CONFLICT 확인.
    Flask test_client는 스레드 세이프하지 않으므로 각각 별도 클라이언트를 생성한다.
    """
    with freeze_time("2025-01-05T09:00:00+09:00"):
        service_id = _insert_service(db)
        start_iso = "2025-01-06T00:00Z"

        results = List[Tuple[int, dict]] = []

        def worker():
            with app.test_client() as c:
                resp = c.post("/api/bookings", json=_payload(service_id, start_iso))
                try:
                    results.append((resp.status_code, resp.get_json()))
                except Exception:
                    results.append((resp.status_code, {"ok": None}))

        # 두 스레드 동시 발사
        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t1.start()
        t1.join(); t2.join()

        # 정확히 1건 성공(200), 1건 충돌(409)
        codes = sorted([rc for rc, _ in results])
        assert codes == [200, 409], results

        ok_flags = [j.get("ok") for _, j in results]
        assert ok_flags.count(True) == 1 and ok_flags.count(False) == 1, results

        # 충돌 응답의 에러 코드 확인
        conflict = next(j for (_, j) in results if j.get("ok") is False)
        assert conflict.get("error", {}).get("code") in {"ERR_CONFLICT", "ERR_SLOT_BLOCKED"}

        # DB에는 단 한 건만 존재
        assert _count_bookings(db, service_id, start_iso) == 1


@pytest.mark.usefixtures("lang_ko")
def test_conflict_error_schema(client: FlaskClient, db: Database, freeze_time):
    with freeze_time("2025-01-05T09:00:00+09:00"):
        service_id = _insert_service(db)
        start_iso = "2025-01-06T00:00Z"

        # 최초 성공으로 슬롯 점유
        r_ok = client.post("api/bookings", json=_payload(service_id, start_iso))
        assert r_ok.status_code == 200
        assert r_ok.get_json().get("ok") is True

        # 동일 슬롯 재요청 -> 에러 스키마 검증
        r = client.post("/api/bookings", json = _payload(service_id, start_iso))
        assert r.status_code == 409
        j = r.get_json()
        assert isinstance(j, dict)
        assert j.get("ok") is False
        err = j.get("error") or {}
        assert set(err.keys()) >= {"code", "message"}
        assert err["code"] in {"ERR_CONFLICT", "ERR_SLOT_BLOCKED"}
