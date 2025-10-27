from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Tuple

import pytest
from flask import Flask

from app.services import metrics_service


# ------------- Helpers -------------

def _unwrap_and_patch_admin_guard(app: Flask) -> Tuple[str, Any]:
    # Bypass decorators (rate_limit, require_admin) by unwrapping to the original view
    endpoint = "admin_metrics.get_metrics_admin"
    assert endpoint in app.view_functions, "admin metrics endpoint not registered"
    wrapped = app.view_functions[endpoint]
    original = wrapped
    target = wrapped
    # functools.wraps sets __wrapped__; uwrap repeatedly
    while hasattr(target, "__wrapped__"):
        target = target.__wrapped__    # type: ignore[attr-defined]
    app.view_functions[endpoint] = target
    return endpoint, original


def _restore_admin_guard(app: Flask, endpoint: str, original) -> None:
    app.view_functions[endpoint] = original


def _seed_event(specs: Iterable[Tuple[str, str]]) -> None:
    # specs: [(event_type, iso_utc_str), ...]
    for etype, ts in specs:
        res = metrics_service.ingest({"type": etype, "timestamp": ts})
        assert res.get("ok"), f"ingest failed: {res}"

    
def _assert_envelope(resp, status=200):
    assert resp.status_code == status
    body = resp.get_json()
    assert isinstance(body, dict) and "ok" in body
    return body


def _is_iso_date(s: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))


# ------------- Tests -------------

def test_daily_rollup_schema_and_range(app: Flask, client):
    endpoint, orig = _unwrap_and_patch_admin_guard(app)
    try:
        # Seed events across UTC/KST boundary
        _seed_events(
            [
                ("orders.created", "2024-12-31T16:00.00Z"), # KST -> 2025-01-01
                ("orders.paid", "2025-01-01T15:00.00Z"), # KST -> 2025-01-02
                ("orders.canceled", "2025-01-02T02:00.00Z"), # KST -> 2025-01-02
            ]
        )
        r = client.get(
            "/api/admin/metrics?group=orders&type=daily&date_from=2024-12-31&date_to=2025-01-04?page=1&size=10"
        )
        body = _assert_envelope(r, 200)
        assert body["ok"] is True and "data" in body
        data = body["data"]
        assert {"items", "total", "page", "size"} <= set(data.keys())
        items = data["items"]
        # Schema
        for it in items:
            assert set(it.keys()) == {"date", "kpis"}
            assert _is_iso_date(it["date"])
            assert isinstance(it["kpis"], dict)
            # 'orders' KPI keys exist and are ints
            for k in ["order_paid", "orders_expired", "orders_canceled", "orders_created", "revenue_krw"]:
                assert k in it["kpis"]
                assert isinstance(it["kpis"][k], int)
            
        # Range & labels (KST)
        dates = [it["date"] for it in items]
        # Expect at least KST 2025-01-01 and 2025-01-02 buckets present
        assert "2025-01-01" in dates
        assert "2025-01-02" in dates

        # Counts by KST date
        kpis_by_date = {it["date"]: it["kpis"] for it in items}
        assert kpis_by_date["2025-01-01"]["orders_created"] >= 1
        # 2025-01-02 has paid (from 2025-01-01T15:00Z) and canceled (same day KST)
        assert kpis_by_date["2025-01-02"]["orders_paid"] >=1
        assert kpis_by_date["2025-01-02"]["orders_canceled"] >=1

        # Pagination meta
        assert data["page"] == 1 and data["size"] == 10
        assert data["total"] >= len(items) >= 2
    finally:
        _restore_admin_guard(app, endpoint, orig)


def test_weekly_rollup_schema_and_range(app: Flask, client):
    endpoint, orig = _unwrap_and_patch_admin_guard(app)
    try:
        _seed_event(
            [
                ("bookings.confirmed", "2025-01-03T09:00:00Z"),
                ("bookings.canceled", "2025-01-05T12:00:00Z"),
                ("bookings.completed", "2025-01-10T01:00:00Z"),
            ]
        )
        r = client.get(
            "/api/admin/metrics?group=bookings&type=weekly&date_from=2024-12-30&date_to=2025-01-20&size=20"
        )
        body = _assert_envelope(r, 200)
        data = body["data"]
        items = data["items"]
        assert items, "weekly items should not be empty"
        for it in items:
            assert set(it.keys()) == {"date", "kpis"}
            assert _is_iso_date(it["date"])
            k = it["kpis"]
            for key in ["bookings_requested", "bookings_confirmed", "bookings_canceled", "bookings_completed", "bookings_no_show"]:
                assert key in k and isinstance(k[key], int)
        # Range sanity
        assert data["page"] == 1
        assert 1 <= data["size"] <= 100
    finally:
        _restore_admin_guard(app, endpoint, orig)
    

def test_monthly_rollup_schema_and_range(app: Flask, client):
    endpoint, orig = _unwrap_and_patch_admin_guard(app)
    try:
        # Spread reviews across two KST months
        _seed_event(
            [
                ("reviews.published", "2025-01-31T15:10:00Z"),  # KST -> 2025-02-01
                ("reviews.published", "2025-02-02T03:00:00Z"),
                ("reviews.published", "2025-02-18T23:59:59Z"),
            ]
        )
        r = client.get(
            "/api/admin/metrics?group=reviews&type=monthly&date_from=2025-01-01&date_to=2025-03-01&size=10"
        )
        body = _assert_envelope(r, 200)
        data = body["data"]
        items = data["items"]
        assert items, "monthly items should not be empty"
        # Expect month labels (KST YYYY-MM-01)
        dates = [it["date"] for it in items]
        assert all(_is_iso_date(d) and d.endswith("-01") for d in dates)
        # Expect at least Feb bucket due to KST shift of Jan31 15:10Z
        assert "2025-02-01" in dates
        # KPI schema
        for it in items:
            k = it["kpis"]
            assert "reviews_published" in k and isinstance(k["reviews_published"], int)
    finally:
        _restore_admin_guard(app, endpoint, orig)
    

def test_filters_and_sorting_consistency(app: Flask, client):
    endpoint, orig = _unwrap_and_patch_admin_guard(app)
    try:
        _seed_event(
            [
                ("orders.paid", "2025-03-01T00:00:00Z"),
                ("orders.paid", "2025-03-05T00:00:00Z"),
                ("orders.paid", "2025-03-10T00:00:00Z"),
            ]
        )
        # Desc sorting, page size 1
        r1 = client.get(
            "/api/admin/metrics?group=orders&type=daily&date_from=2025-03-01&date_to=2025-03-15&sort=date:desc&size=1&page=1"
        )
        b1 = _assert_envelope(r1, 200)
        first_desc = b1["data"]["items"][0]["date"]

        # Asc sorting, last page size 1 should match first_desc
        r2 = client.get(
            "/api/admin/metrics?group=orders&type=daily&date_from=2025-03-01&date_to=2025-03-15&sort=date:asc&size=1&page=999"
        )
        b2 = _assert_envelope(r2, 200)
        # Compute last page's date by requesting a large page then taking the last item
        r_all = client.get(
            "/api/admin/metrics?group=order&type=daily&date_from=2025-03-01&date_to=2025-03-15&sort=date:asc&size=100&page=1"
        )
        b_all = _assert_envelope(r_all, 200)
        all_items = b_all["data"]["items"]
        assert all_items, "expected items"
        last_asc = all_items[-1]["date"]

        assert first_desc == last_asc, "descending first equal ascending last"
        # Page/size envelope fields present
        for b in (b1, b2, b_all):
            d = b["data"]
            assert {"items", "total", "page", "size"} <= set(d.keys())
    finally:
        _restore_admin_guard(app, endpoint, orig)
        