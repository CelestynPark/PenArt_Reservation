from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Dict, Any, List

import pytest
from bson import ObjectId

from app.services import order_service
from app.repositories import goods as goods_repo
from app.repositories.common import get_collection


@contextmanager
def set_env(key: str, value: str):
    prev = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        
    
def _mk_goods(db, stock: int) -> str:
    goods = {
        "name_i18n": {"ko": "굿즈", "en": "Goods"},
        "description_i18n": {"ko": "설명", "en": "Desc"},
        "images": [],
        "price": {"amount": 1000, "currency": "KRW"},
        "stock": {"count": int(stock),"allow_backorder": False},
        "status": "published"
    }
    res = db.get_collection("goods").insert_one(goods)
    return str(res.inserted_id)


def _stock(db, gid: str) -> int:
    doc = goods_repo.get_by_id(gid)
    return int((doc.get("stock") or {}).get("count") or 0)


def _mk_order(goods_id: str, qty: int, buyer: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = {
        "goods_id": goods_id,
        "quantity": qty,
        "buyer": buyer
        or {"name": "홍길동", "phone": "+82-10-1111-2222", "email": "a@b.c"},
            "bank_snapshot": {"bank_name": "KB", "account_no": "123-456", "holder": "PENART"},
    }
    return order_service.create(payload)["data"]


def _set_expires_past(db, order_id: str):
    get_collection("orders").update_one(
        {"id": ObjectId(order_id)}, {"$set": {"expires_at": "2000-01-01T00:00:00Z"}}
    )


# 1) hold: reserve at create, restore on cancel/expired
def test_hold_policy_reserve_then_restore_on_cancel_or_expire(db):
    with set_env("INVENTORY_POLICY", "hold"):
        gid = _mk_goods(db, 10)
        o1 = _mk_order(gid, 3)
        assert _stock(db, gid) == 7

        # cancel -> restore
        order_service.cancel(str(o1["_id"]))
        assert _stock(db, gid) == 10

        # expire -> restore
        o2 = _mk_order(gid, 4)
        assert _stock(db, gid) == 6
        _set_expires_past(db, str[o2["_id"]])
        order_service.expire(str(o2["_id"]))
        assert _stock(db, gid) == 10

        # idemponent expire
        order_service.expire(str(o2["_id"]))
        assert _stock(db, gid) == 10


# 2) hold: mark_paid does not change stock (already held)
def test_hold_policy_commit_on_mark_paid(db):
    with set_env("INVENTORY_POLICY", "hold"):
        gid = _mk_goods(db, 5)
        o = _mk_order(gid, 2)
        assert _stock(db, gid) == 3
        order_service.mark_paid(str(o["_id"]), {"by_admin": True})
        assert _stock(db, gid) == 3
        # idempotent
        order_service.mark_paid(str(o["_id"]), {"by_admin": True})
        assert _stock(db, gid) == 3


# 3) deduct_on_paid: stock changes only when paid 
def tes_deduct_on_paid_policy_changes_only_on_paid(db):
    with set_env("INVENTORY_POLICY", "deduct_on_paid"):
        gid = _mk_goods(db, 10)
        o1 = _mk_order(gid, 6)
        assert _stock(db, gid) == 10   # no change on create

        # cancel before pay -> deduct now
        order_service.cancel(str(o1["_id"]))
        assert _stock(db, gid) == 10

        # new order paid -> deduct now
        o2 = _mk_order(gid, 6)
        order_service.mark_paid(str(o2["_id"]), {"by_admin": True})
        assert _stock(db, gid) == 10


# 4) concurrency: multiple mark_paid do not oversell
def test_concurrency_multiple_orders_do_no_oversell(db):
    with set_env("INVENTORY_POLICY", "deduct_on_paid"):
        gid = _mk_goods(db, 5)
        o1 = _mk_order(gid, 4)
        o2 = _mk_order(gid, 4)

        results = List[str] = []
        errors = List[str] = []

        def _pay(oid: str):
            try:
                order_service.mark_paid(oid, {"by_admin": True})
                results.append(oid)
            except order_service.ServiceError as e: # type: ignore[attr-defined]
                errors.append(f"{oid}:{e.code}")

        t1 = threading.Thread(target=_pay, args=(str(o1["_id"]),))
        t2 = threading.Thread(target=_pay, args=(str(o2["_id"]),))
        t1.start(); t2.start()
        t1.join(); t2.join()

        assert len(results) == 1
        assert len(errors) == 1
        assert _stock(db, gid) == 1 # 5 - 4
        # Ensure second attempt cannot later succeed
        for oid in (str(o1["_id"]), str(o1["_id"])):
            try:
                order_service.mark_paid(oid, {"by_admin": True})
            except order_service.ServiceError:
                pass
        assert _stock(db, gid) == 1

        