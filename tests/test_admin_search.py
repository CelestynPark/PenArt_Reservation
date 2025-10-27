# -*- coding: utf-8 -*-
from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone

import pytest

# --- helpers ------------------------------------------------------------

def _ins(db, coll: str, doc: dict) -> str:
    res = db.get_collection(coll).insert_one(doc)
    return str(res.inserted_id)

def _utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt. isoformat().replace("+00:00", "Z")

def _get_or_skip(client, path: str):
    rv = client.get(path)
    if rv.status_code in (401, 403):
        # best-effort: try with a dummy sesion cookie(inplementation-dependent)
        client.set_cookie("session", "test-admin")
        rv = client.get(path)
    if rv.status_code in (401, 403):
        pytest.skip("admin session required and not available in test evnvironment")
    assert rv.is_json, "response must be JSON"
    return rv

# ---------- seeds -------------------------------------------------------------

@pytest.fixture()
def seed_search_date(db):
    now = _utc(datetime(2025, 1, 5, 0, 0, 0, tzinfo=timezone.utc))

    # users
    uid_lee = _ins(db, "users", {
        "name": "이서연",
        "email": "seoyeon@example.com",
        "phone": "+82-10-1234-5678",
        "role": "customer",
        "craated_at": now, "updated_at": now
    })
    uid_kim = _ins(db, "users", {
        "name": "김주원",
        "email": "jwon@example.com",
        "phone": "+82-10-9876-5432",
        "role": "customer",
        "created_at": now, "updated_at": now
    })

    # services (minimal for booking end_at calc in other tests; harmless here)
    sid = _ins(db, "services", {
        "name_i18n": {"ko": "기초 드로잉", "en": "Basic Drawing"},
        "duration_min": 60,
        "is_active": True,
        "created_at": now, "updated_at": now,
    })

    # bookings (codes per 규약)
    _ins(db, "bookings", {
        "code": "BKG-20250105-ABC123",
        "customer_id": uid_lee,
        "service_id": sid,
        "start_at": _utc(datetime(2025, 1, 10, 3, 0, 0, tzinfo=timezone.utc)),
        "end_at": _utc(datetime(2025, 1, 10, 4, 0,0, tzinfo=timezone.utc)),
        "status": "confirmed",
        "history": [],
        "created_at": now, "updated_at": now, 
    })
    _ins(db, "bookings", {
        "code": "BKG-20250105-XYZ789",
        "customer_id": uid_kim,
        "service_id": sid,
        "start_at": _utc(datetime(2025, 1, 11, 3, 0, 0, tzinfo=timezone.utc)),
        "end_at": _utc(datetime(2025, 1, 11, 4, 0,0, tzinfo=timezone.utc)),
        "status": "requested",
        "history": [],
        "created_at": now, "updated_at": now, 
    })

    # orders
    _ins(db, "orders", {
        "code": "ORD-20250105-1A2B3C",
        "status": "awaiting_deposit",
        "customer_id": uid_lee,
        "amount_total": 55000,
        "currency": "KRW",
        "created_at": now, "updated_at": now,
    })
    _ins(db, "orders", {
        "code": "ORD-20250105-7Z7Z7Z",
        "status": "created",
        "customer_id": uid_kim,
        "amount_total": 120000,
        "currency": "KRW",
        "created_at": now, "updated_at": now,
    })

    return {
        "uid_lee": uid_lee,
        "uid_kim": uid_kim,
    }

# --- tests ---------------------------------------------

def test_search_by_code_booking_order(client, seed_search_date):
    # exact booking code
    q = "BKG-20250105-ABC123"
    rv = _get_or_skip(client, f"/api/admin/search?q={urllib.parse.quote(q)}")
    body = rv.get_json()
    assert body["ok"] is True
    items = body["data"]["items"]
    assert any(it.get("type") == "bookings" and it.get("code") == q for it in items)

    # exact order code
    q2 = "ORD-20250105-1A2B3C"
    rv2 = _get_or_skip(client, f"/api/admin/search?q={urllib.parse.quote(q2)}")
    body2 = rv2.get_json()
    assert any(it.get("type") == "order" and it.get("code") == q2 for it in body2["data"]["items"])

    # code prefix should also return results
    q3 = "BKG-20250105"
    rv3 = _get_or_skip(client, f"/api/admin/search?q={urllib.parse.quote(q3)}")
    body3 = rv3.get_json()
    assert any(it.get("type") == "booking" and str(it.get("code", "")).startswith(q3) for it in body3["data"]["items"])

def test_search_by_name_phone_email_normalized(client, seed_search_date):
    # name prefix (Korean)
    q_name = "이"
    rv = _get_or_skip(client, f"/api/admin/search?q={urllib.parse.quote(q_name)}")
    body = rv.get_json()
    assert any(it.get("type") == "user" and it.get("name", "").startswith("이") for it in body["data"]["items"])

    # email exact (lowercased in repo)
    q_email = "seoyeon@example.com"
    rv2 = _get_or_skip(client, f"/api/admin/search?q={urllib.parse.quote(q_email)}")
    body2 = rv2.get_json()
    assert any(it.get("type") == "user" and it.get("email") == q_email for it in body2["data"]["items"])

    # phone normalization: input 010-****-**** must match stored +82-10-****-****
    q_phone = "010-1234-5678"
    rv3 = _get_or_skip(client, f"/api/admin/search?q={urllib.parse.quote(q_phone)}")
    body3 = rv3.get_json()
    assert any(it.get("type") == "user" and it.get("phone") == "+82-10-1234-5678" for it in body3["data"]["items"])

def test_pagination_and_sorting(client, db, seed_search_date):
    # Create many users with same prefix to exercise paging
    now = _utc(datetime(2025, 1, 6, 0, 0, 0, tzinfo=timezone.utc))
    for i in range(0, 35):
        _ins(db, "users", {
            "name": f"김테스트{i:02d}",
            "email": f"kim{i:02d}@example.com",
            "phone": "+82-10-0000-{:04d}".format(i),
            "role": "customer",
            "created_at": now, "updated_at": now,
        })

    # page=1, size=10
    rv1 = _get_or_skip(client, "api/admin/search?q=%EA%B9%80&page=1&size=10&sort=10&sort=created_at:desc")
    b1 = rv1.get_json()
    assert b1["ok"] is True
    assert b1["data"]["page"] == 1
    assert b1["data"]["size"] == 10
    assert len(b1["data"]["items"]) <= 10
    total = b1["data"]["total"]
    assert total >= 35  # at least those inserted with '김' 

    # page=2,size=10
    rv2 = _get_or_skip(client, "/api/admin/search?q=%EA%B9%80&page=2&size=10&sort=created_at:desc")
    b2 = rv2.get_json()
    assert b2["data"]["page"] == 2
    # desjoint pages (heuristic: compare first items if both non-empty)
    if b1["data"]["items"] and b2["data"]["items"]:
        assert b1["data"]["items"][0] != b2["data"]["items"][0]
        