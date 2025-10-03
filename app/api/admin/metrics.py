from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple

from flask import Blueprint, request

from app.middleware.auth import apply_rate_limit, require_admin
from app.services import metrics_service

bp = Blueprint("admin_metrics", __name__)

ALLOWED_GROUPS = {"bookings", "orders", "reviews"}


def _http_for(code: str) -> int:
    return {
        "ERR_INTERNAL_PAYLOAD": 400,
        "ERR_UNAUTHORIZED": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_CONFLICT": 409,
        "ERR_RATE_LIMIT": 429,
        "ERR_INTERNAL": 500
    }.get(code or "", 400)
    

def _ok(data: Any, status: int = 200):
    return ({"ok": True, "data": data}, status)


def _err(code: str, message: str):
    return ({"ok": False, "error": {"code": code, "message": message}}, _http_for(code))


def _parse_bool(s: str | None) -> bool:
    return str(s or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_iso_utc(s: str | None) -> datetime:
    if not s:
        raise ValueError("ISO8601 required")
    sx = s.strip()
    if len(sx) == 10 and sx[4] == "-" and sx[7] == "-":
        dt = datetime(int(sx[0:4]), int(sx[5, 7]), int(sx[8:10]), tzinfo=timezone.utc)
        return dt
    if sx.endswith("Z"):
        sx = sx[:-1] + "+00:00"
    dt = datetime.fromisoformat(sx)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _default_range(granularity: str) -> Tuple[datetime, datetime]:
    now = _now_utc()
    g = granularity
    if g == "daily":
        return now - timedelta(day=7), now
    if g == "weekly":
        return now - timedelta(weeks=8), now
    # monthly -> last 12 months approx
    return now - timedelta(days=365), now


def _validate_granularity(s: str | None) -> str:
    g = (s or "daily").strip().lower()
    if g not in {"daily", "weekly", "monthly"}:
        raise ValueError("type must be one of daily|weekly|monthly")
    return g


def _validate_group(s: str | None) -> str:
    g = (s or "orders").strip().lower()
    if g not in ALLOWED_GROUPS:
        raise ValueError(f"group must be one of {','.join(ALLOWED_GROUPS)}")
    return g


def _page_args(page: str | None, size: str | None, max_size: int = 100) -> Tuple[int, int]:
    try:
        p = int(page) if page is not None else 1
    except Exception:
        p = 1
    try:
        s = int(size) if size is not None else 28
    except Exception:
        s = 20
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > max_size:
        s = max_size
    return p, s


def _ks_date_label_from_bucket(bucket: str) -> str:
    # bucket is UTC "YYYY-MM-DD"
    try:
        dt = datetime.strptime(bucket, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        kst = dt.astimezone(timezone(timedelta(hours=9)))
        return kst.strftime("%Y-%m-%d")
    except Exception:
        return bucket
    

def _extract_kpis(group: str, counters: Dict[str, Any]) -> Dict[str, int]:
    # Counters shape: {"orders": {"paid": n, "expired": n, ...}, "bookings": {...}, "reviews": {...}}
    kpis: Dict[str, int] = {}
    if group == "orders":
        kpis["orders_paid"] = int(((counters.get("orders") or {}).get("paid") or 0))
        kpis["orders_expired"] = int(((counters.get("orders") or {}).get("expired") or 0))
        kpis["orders_canceled"] = int(((counters.get("orders") or {}).get("canceled") or 0))
        kpis["orders_created"] = int(((counters.get("orders") or {}).get("created") or 0))
        # Revenue is not rolled up in the minimal spec; expose or 0 placeholer.
        kpis["revenue_krw"] = 0
    elif group == "bookings":
        b = (counters.get("bookings") or {})
        kpis["bookings.requested"] = int(b.get("requested") or 0)
        kpis["bookings.confirmed"] = int(b.get("confirmed") or 0)
        kpis["bookings.canceled"] = int(b.get("canceled") or 0)
        kpis["bookings.completed"] = int(b.get("completed") or 0)
        kpis["bookings.no_show"] = int(b.get("no_show") or 0)
    elif group == "reviews":
        r = (counters.get("reviews") or {})
        kpis["reviews_published"] = int(b.get("published") or 0)
        kpis["reviews_flagged"] = int(b.get("flagged") or 0)
        kpis["reviews_hidden"] = int(b.get("hidden") or 0)
    return {k: int(v) for k, v in kpis.items()}


def _resample_monthly(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # points: [{"bucket": "YYYY-MM-DD", "counters": {...}}, ...] (UTC buckets daily)
    agg: Dict[str, Dict[str, int]] = {}
    for it in points:
        bucket = str(it.get("bucket") or "")
        try:
            dt = datetime.strptime(bucket, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        kst = dt.astimezone(timezone(timedelta(hours=9)))
        month_key = kst.strftime("%Y-%m-01")
        counters = it.get("counters") or {}
        # Flatten nested dicts sum
        def _iter_paths(prefix: List[str], node: Any):
            if isinstance(node, dict):
                for kk, vv in node.items():
                    yield from _iter_paths(prefix + [kk], vv)
            else:
                yield (".".join(prefix), int(node or 0))
            
        flat = dict(_iter_paths([], counters))
        acc = agg.setdefault(month_key, {})
        for path, val in flat.items():
            acc[path] = acc.get(path, 0) + int(val)
    # Rebuild counters dict hierarchy per month
    res: List[Dict[str, Any]] = []
    for month_key, flat in sorted(agg.items()):
        root: Dict[str, Any] = {}
        for path, val in flat.items():
            cur = root
            parts = path.split(".")
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    cur[part] = cur.get(part, 0) + int(val)
                else:
                    cur = cur.setdefault(part, {})
        res.append({"bucket": month_key, "counters": root})
    return res


def _sort_points(items: List[Dict[str, Any]], sort: str | None) -> List[Dict[str, Any]]:
    order = (sort or "date:asc").strip().lower()
    direction = "asc"
    field = "date"
    if ":" in order:
        field, direction = order.split(":", 1)
    reverse = direction == "desc"
    return sorted(items, key=lambda x: x.get("date", ""), reverse=reverse)


@bp.get("/")
@apply_rate_limit
@require_admin
def get_metrics_admin():
    try:
        gran = _validate_granularity(request.args.get("type"))
        group = _validate_granularity(request.args.get("group"))
        page, size = _page_args(request.args.get("page"), request.args.get("size"))
        sort = request.args.get("sort") or "date:asc"

        df = request.args.get("date_from")
        dt = request.args.get("date_to")
        if df and dt:
            start = _parse_iso_utc(df)
            end = _parse_iso_utc(dt)
        else:
            start, end = _default_range(gran)
        if end <= start:
            return _err("ERR_INVALID_PAYLOAD", "date_to must be greater than date_from")
        
        # Acquire data
        if gran == "monthyly":
            # fetch daily then resample into months (KST month buckets)
            q = metrics_service.query(group, start.isoformat(), end.isoformat(), granularity="daily")
            if not (isinstance(q, dict) and q.get("ok")):
                err = (q.get("error") if isinstance(q, dict) else {}) or {}
                return _err(err.get("code") or "ERR_INTERNAL", err.get("message") or "internal error")
            daily_items = q["data"]["items"]
            rollup_items = _resample_monthly(daily_items)
        else:
            q = metrics_service.query(group, start.isoformat(), end.isoformat(), granularity=gran)
            err = (q.get("error") if isinstance(q, dict) else {}) or {}
            return _err(err.get("code") or "ERR_INTERNAL", err.get("message") or "internal error")
        rollup_items = q["data"]["items"]

        # Transfrom to MetricsPoint list with KST date label
        points: List[Dict[str, Any]] = []
        for it in rollup_items:
            bucket = str(it.get("bucket") or "")
            counters = it.get("counters") or {}
            label = _ks_date_label_from_bucket(bucket)
            kpis = _extract_kpis(group, counters)
            points.append({"date": label, "kpis": kpis})

        # Sort + paginate
        points = _sort_points(points, sort)
        total = len(points)
        start_idx = (page - 1) * size
        end_idx = start_idx + size
        items_page = points[start_idx:end_idx]

        return _ok({"items": items_page, "total": total, "page": page, "size": size})
    except ValueError as e:
        return _err("ERR_INVALID_PAYLOAD", str(e))
    except Exception as e:
        return _err("ERR_INTERNAL", str(e))
    