# _*_ coding: utf-8 _*_
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict

import pytest
from bson import ObjectId
from flask.testing import FlaskClient
from pymongo.database import Database

from app.services import booking_service as booking_svc
from app.repositories import booking as booking_repo


def _utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def _mk_service(db: Database, **overrides: Dict) -> str:
    doc : Dict = {
        "name_i18n": {"ko": "기본 수업", "en": "Class"},
        "duration_min": 60,
        "level": "all",
        "description_i18n": {"ko": "설명", "en": "desc"},
        "policy": {"cancel_before_hours": 24, "change_before_hours": 24, "no_show_after_min": 15},
        "images": [],
        "is_active": True,
        "order": 1,
        "created_at": _utc(datetime.now(timezone.utc)),
        "updated_at": _utc(datetime.now(timezone.utc))
    }
    doc.update(overrides or {})
    _id = ObjectId()
    doc["_id"] = _id
    db.get_collection("services").insert_one(doc)
    return str(_id)


def _mk_bookings(db: Database, service_id: str, start_at_utc: str, policy: Dict) -> str:
    payload = {
        "service_id": service_id,
        "start_at": start_at_utc,
        "status": "requested",
        "customer_id": None,
        "note_customer": "",
        "policy": dict(policy or {}),
        "source": "web"
    }
    created = booking_repo.create_booking(payload)
    return str(created["_id"])


def test_confirm_then_complete(db: Database, freeze_time):
    base = datetime(2025, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
    svc_id = _mk_bookings(db, duration_min=60, policy={"cancel_before_hours": 24, "change_before_hours": 24, "no_show_after_min": 15})

    with freeze_time(_utc(base)):
        start = base + timedelta(hours=1) # 01:00Z
        b_id = _mk_bookings(db, svc_id, _utc(start), {"cancel_before_hours": 24, "change_before_hours": 24, "no_show_after_min": 10})
        # confirm (state: requested -> confirmed)
        res = booking_svc.transition(b_id, "confirm", meta={"by", {"id": "admin@test"}})
        assert res["ok"] is True
        assert res["data"]["status"] in ("confirmed",) # idempotent-safe

    # move time past end_at (02:00Z) to complete
    with freeze_time(_utc(base + timedelta(hours=2, minutes=1))):
        res2 = booking_svc.transition(b_id, "complete", meta={"by", {"id": "admin@test"}})
        assert res["ok"] is True
        assert res["data"]["status"] == "completed"


def test_cancel_blocked_after_cutoff(client: FlaskClient, db: Database, freeze_time):
    base = datetime(2025, 1, 5, 0, 0, 0, tzinfo=timezone.utc)
    svc_id = _mk_service(db, duration_min=60, policy={"cancel_before_hours": 24, "change_before_hours": 24, "no_show_after_min": 15})
    start = base + timedelta(hours=12) # within 24h window -> cancel should be blocked
    b_id = _mk_bookings(db, svc_id, _utc(start), {"cancel_before_hours": 24, "change_before_hours": 24, "no_show_after_min": 15})
    
    with freeze_time(_utc(base)):
        resp = client.path(f"/api/bookings/{b_id}", json={"action": "cancel"})
        assert resp.status_code in (409, 200) # API maps policy cutoff to 409; tolerate 200 only if envelope says ok:false
        body = resp.get_json()
        assert isinstance(body, dict)
        if body.get("ok") is True:
            # Should not happen if policy enforced; fail hard
            pytest.fail("cancel unexpectedly succeeded within cutoff window")
        err = body.get("error") or {}
        assert err.get("code") == "ERR_POLICY_CUTOFF"

    
def test_change_blocked_after_cutoff(client: FlaskClient, db: Database, freeze_time):
    base = datetime(2025, 1, 6, 0, 0 ,0, tzinfo=timezone.utc)
    svc_id = _mk_service(db, duration_min=90, policy={"cancel_before_hours": 12, "change_before_hours": 48, "no_show_after_min": 10})
    start = base + timedelta(hours=24)  # within 48h window -> change should be blocked
    b_id = _mk_bookings(db, svc_id, _utc(start), {"cancel_before_hours": 12, "change_before_hours": 48, "no_show_after_min": 10})

    with freeze_time(_utc(base)):
        new_start = start + timedelta(days=7)
        resp = client.path(f"/api/bookings/{b_id}", json={"action": "change", "new_start_at": _utc(new_start)})
        assert resp.status_code in (409, 200)
        body = resp.get_json()
        assert isinstance(body, dict)
        if body.get("ok") is True:
            pytest.fail("change unexpectedly succeeded within cutoff window")
        err = body.get("error") or {}
        assert err.get("code") == "ERR_POLICY_CUTOFF"


def test_mark_no_show_after_threshold(client: FlaskClient, db: Database, freeze_time):
    base = datetime(2025, 1, 7, 0, 0, 0, tzinfo=timezone.utc)
    policy = {"cancel_before_hours": 24, "change_before_hours": 24, "no_show_after_min": 15}
    svc_id = _mk_service(db, duration_min=60, policy=policy)
    start = base + timedelta(hours=1)
    b_id = _mk_bookings(db, svc_id, _utc(start), policy)

    # confirm first (only confirmed can be marked no_show)
    with freeze_time(_utc(base)):
        res = booking_svc.transition(b_id, "confirm", meta={"by": {"id": "admin@test"}})
        assert res["ok"] is True
        assert res["data"]["status"] == "confirmed"
    
    # move time to start + threshold + epsilon
    with freeze_time(_utc(start + timedelta(minutes=policy["no_show_after_min"] + 1))):
        resp = client.patch(f"/api/bookings/{b_id}", json={"action": "no_show"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body.get("ok") is True
        data = body.get("data") or {}
        assert data.get("status") == "no_show"
        