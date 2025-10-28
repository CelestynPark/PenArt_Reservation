from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Dict

import pytest

from app.services import order_service as svc
from app.repositories import order as order_repo
from app.repositories.common import get_collection


def _insert_goods(db, stock: int = 5, price: int = 10000, allow_backorder: bool = False, status: str = "published") -> str:
    doc = {
        "name_i18n": {"ko": "굿즈", "en": "Goods"},
        "description_i18n": {"ko": "설명", "en": "Desc"},
        "images": [],
        "price": {"amount": price, "currency": "KRW"},
        "stock": {"count": stock, "allow_backorder": allow_backorder},
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    res = get_collection("goods").insert_one(doc)
    return str(res.inserted_id)


def _create_order_payload(goods_id: str, qty: int = 2) -> Dict:
    return {
        "goods_id": goods_id,
        "quantity": qty,
        "buyer": {"name": "Tester", "phone": "+82-10-1234-5678", "email": "t@example.com"},
        "bank_snapshot": {"bank_name": "KB", "account_no": "123-456-7890", "holder": "PENART"},
    }


def _goods_stock() -> int:
    doc = get_collection("goods").find_one({})
    return int(((doc or {}).get("stock") or {}).get("count", 0))


def _first_history_to(doc) -> str:
    hist = (doc or {}).get("history") or []
    return hist[0].get("to") if hist else ""


@pytest.mark.usefixtures("lang_ko")
def test_create_order_sets_expiry_and_history(client, db, freeze_time, monkeypatch):
    goods_id = _insert_goods(db, stock=5, price=12000)
    # Default policy is hold; ensure it via monkeypatch
    monkeypatch.setattr(svc, "_policy", lambda: "hold")
    with freeze_time("2025-01-05T00:00:00Z"):
        resp = client.post(
            "/api/orders",
            json=_create_order_payload(goods_id, qty=2),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True
        data = body["data"]
        assert data["status"] == "awaiting_deposit"
        # expires_at = now + 48h (ORDER_EXPIRE_HOURS default)
        exp = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        assert exp == datetime(2025, 1, 7, 0, 0, 0, tzinfo=timezone.utc)
        # Check DB persisted fields & history bootstrap
        doc = order_repo.find_by_id(data["id"])
        assert doc is not None
        assert doc["amount_total"] == 24000
        assert _first_history_to(doc) == "awaiting_deposit"
        # Policy=hold reserved stock immediately
        assert _goods_stock() == 3


@pytest.mark.usefixtures("lang_ko")
def test_expire_order_is_idempotent_and_restores_stock_when_hold(db, freeze_time, monkeypatch):
    goods_id = _insert_goods(db, stock=5, price=10000)
    monkeypatch.setattr(svc, "_policy", lambda: "hold")
    with freeze_time("2025-02-01T12:00:00Z"):
        res = svc.create(_create_order_payload(goods_id, qty=2))
        assert res["ok"] is True
        order = res["data"]
        oid = str(order["_id"])
        assert _goods_stock() == 3
    # Move time past expiry (48h)
    with freeze_time("2025-02-03T13:00:00Z"):
        before_hist_len = len(order_repo.find_by_id(oid)["history"])
        r1 = svc.expire(oid)
        assert r1["ok"] is True
        doc1 = r1["data"]
        assert doc1["status"] == "expired"
        assert _goods_stock() == 5  # released hold
        # Idempotent second call
        r2 = svc.expire(oid)
        assert r2["ok"] is True
        doc2 = r2["data"]
        assert doc2["status"] == "expired"
        assert _goods_stock() == 5
        after_hist_len = len(order_repo.find_by_id(oid)["history"])
        # Only one transition added
        assert after_hist_len == before_hist_len + 1


@pytest.mark.parametrize("policy", ["hold", "deduct_on_paid"])
@pytest.mark.usefixtures("lang_ko")
def test_mark_paid_is_idempotent_and_updates_history(db, freeze_time, monkeypatch, policy):
    goods_id = _insert_goods(db, stock=5, price=7000)
    monkeypatch.setattr(svc, "_policy", lambda: policy)
    with freeze_time("2025-03-10T09:00:00Z"):
        res = svc.create(_create_order_payload(goods_id, qty=2))
        assert res["ok"] is True
        oid = str(res["data"]["_id"])
        # Stock behavior differs per policy
        if policy == "hold":
            assert _goods_stock() == 3
        else:
            assert _goods_stock() == 5
        before_hist_len = len(order_repo.find_by_id(oid)["history"])
        m1 = svc.mark_paid(oid, {"by_admin": True})
        assert m1["ok"] is True
        assert m1["data"]["status"] == "paid"
        # Deduct on paid only when policy==deduct_on_paid
        if policy == "deduct_on_paid":
            assert _goods_stock() == 3
        else:
            assert _goods_stock() == 3
        # Idempotent repeat
        m2 = svc.mark_paid(oid, {"by_admin": True})
        assert m2["ok"] is True
        assert m2["data"]["status"] == "paid"
        after_hist_len = len(order_repo.find_by_id(oid)["history"])
        assert after_hist_len == before_hist_len + 1


@pytest.mark.usefixtures("lang_ko")
def test_cancel_by_admin_is_idempotent(db, freeze_time, monkeypatch):
    goods_id = _insert_goods(db, stock=4, price=5000)
    monkeypatch.setattr(svc, "_policy", lambda: "hold")
    with freeze_time("2025-04-01T00:00:00Z"):
        res = svc.create(_create_order_payload(goods_id, qty=1))
        assert res["ok"] is True
        oid = str(res["data"]["_id"])
        assert _goods_stock() == 3
        before_hist_len = len(order_repo.find_by_id(oid)["history"])
        c1 = svc.cancel(oid, reason="admin_cancel")
        assert c1["ok"] is True
        assert c1["data"]["status"] == "canceled"
        assert _goods_stock() == 4
        c2 = svc.cancel(oid, reason="admin_cancel")
        assert c2["ok"] is True
        assert c2["data"]["status"] == "canceled"
        assert _goods_stock() == 4
        after_hist_len = len(order_repo.find_by_id(oid)["history"])
        assert after_hist_len == before_hist_len + 1
