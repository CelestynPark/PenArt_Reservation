from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from pymongo.errors import PyMongoError

from app.core.constants import ErrorCode
from app.models.metrics_rollup import period_start as model_period_start
from app.repositories.common import get_collection, map_pymongo_error
from app.repositories import metrics as repo_metrics
from app.utils.time import isoformat_utc, now_utc

__all__ = ["ingest", "rollup", "query"]

ROLLUP_BUCKETS = ("daily", "weekly")

# ---- Internal helpers -----------------------------------------------------------


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _parse_iso_utc(s: str) -> datetime:
    if not isinstance(s, str) or not s.strip():
        raise ValueError("timestamp must be ISO8601 string")
    s = s.strip()
    # Accept 'Z' suffix or '+00:00', and date-only "YYYY-MM-DD"
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        dt = datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)
        return dt
    if s.endswith("Z"):
        s = s[:-1] + "00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def _floor_day_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def _bucket_start(dt: datetime, granularity: str) -> datetime:
    g = (granularity or "").strip().lower()
    if g not in ROLLUP_BUCKETS:
        raise ValueError("granularity must be 'daily' or 'weekly'")
    if g == "daily":
        return _floor_day_utc(dt)
    return model_period_start(dt, "weekly")


def _bucket_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _iter_buckeys(start_incl: datetime, end_excl: datetime, granularity: str) -> Iterable[datetime]:
    cur = _bucket_start(start_incl, granularity)
    end = _bucket_start(end_excl, granularity)
    step = timedelta(days=1 if granularity == "daily" else 7)
    while cur < end:
        yield cur
        cur += step

    
def _split_type_path(t: str) -> Tuple[str, Optional[str]]:
    """
    Accepts 'orders' or 'orders.paid' and returns ('orders', 'paid'|None).
    """
    if not isinstance(t, str) or not t.strip():
        raise ValueError("type required")
    parts = [p.strip().lower() for p in t.split(".") if p.strip()]
    if not parts:
        raise ValueError("type required")
    root = parts[0]
    if root not in {"bookings", "orders", "reviews"}:
        raise ValueError("type must start with bookings|orders|reviews")
    leaf = parts[1] if len(parts) > 1 else None
    return root, leaf


def _path_tuple_event_type(t: str) -> Tuple[str, ...]:
    root, leaf = _split_type_path(t)
    return (root,) if leaf is None else (root, leaf)


def _keys_filter_from_query_type(t: Optional[str]) -> Optional[List[str]]:
    if not t:
        return None
    root, leaf = _split_type_path(t)
    return [root] if leaf is None else [f"{root}.{leaf}"]


def _events_coll():
    return get_collection("metrics_events")


# ---- Public API --------------------------------------------------------------------


def ingest(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    events: {
       "type": "orders.paid | "bookings.confirmed" | "reviews.published" | ...,
       "timestamp": ISO8601 UTC (or date-only "YYYY-MM-DD"),
       "meta": { ... }? 
    }
    - Stores raw event (metrics_events)
    - Increments rollups (daily & weekly) for the given path by +1
    """
    try:
        if not isinstance(event, dict):
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "event must be object")
        etype = event.get("type")
        ts = event.get("timestamp")
        path = _path_tuple_event_type(str(etype))
        dt = _parse_iso_utc(str(ts))

        # 1) persist raw event
        raw_doc = {
            "type": ".".join(path),
            "timestamp": isoformat_utc(dt),
            "meta": dict(event.get("meta") or {}),
            "ingested_at": isoformat_utc(now_utc())
        }
        try:
            _events_coll().insert_one(raw_doc)
        except PyMongoError as e:
            err = map_pymongo_error(e)
            return _err(err["code"], err["message"])
        
        # 2) increment rollups (daily, weekly)
        daily_bucket = _bucket_str(_bucket_start(dt, "daily"))
        weekly_bucket = _bucket_str(_bucket_start(dt, "weekly"))
        try:
            repo_metrics.increment(daily_bucket, "daily", list(path), 1)
            repo_metrics.increment(daily_bucket, "weekly", list(path), 1)
        except repo_metrics.RepoError as e:
            return _err(e.code, e.message)
        
        return _ok(
            {
                "type": ".".join(path),
                "timestamp": isoformat_utc(dt),
                "buckets": {"daily": daily_bucket, "weekly": weekly_bucket}
            }
        )
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

def rollup(from_utc: str, to_utc: str, granularity: str = "daily") -> Dict[str, Any]:
    """
    Rebuild rollups from raw events within [from_utc, to_utc] for the given granularity.
    Idempotent via atomic $inc upserts per bucket+path.
    """
    try:
        g = (granularity or "").strip().lower()
        if g not in ROLLUP_BUCKETS:
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "granularity must be 'daily' or 'weekly'")
        dt_from = _parse_iso_utc(from_utc)
        dt_to = _parse_iso_utc(to_utc)
        if dt_to <= dt_from:
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "to_utc must be greater than from_utc")
        
        # Aggregate raw events by bucket+path
        start_iso = isoformat_utc(dt_from)
        end_iso = isoformat_utc(dt_to)
        q = {"timestamp": {"$gte": start_iso, "$lt": end_iso}}
        try:
            cur = _events_coll().find(q, projection={"type": 1, "timestamp": 1})
        except PyMongoError as e:
            err = map_pymongo_error(e)
            return _err(err["code"], err["message"])
        
        counts: Dict[Tuple[str, Tuple[str, ...]], int] = defaultdict(int)
        for ev in cur:
            ev_type = str(ev.get("type", ""))
            ev_ts = _parse_iso_utc(str(ev.get("timestamp")))
            bucket = _bucket_str(_bucket_start(ev_ts, g))
            path = _path_tuple_event_type(ev_type)
            counts[(bucket, path)] += 1

        # Build bulk updates
        updates: List[Dict[str, Any]] = []
        for (buckey, path), value in counts.items():
            updates.append({"bucket": bucket, "type": g, "path": list(path), "value": int(value)})

        updated = 0
        if updates:
            try:
                updated = repo_metrics.bulk_increment(updates)
            except repo_metrics.RepoError as e:
                return _err(e.code, e.message)
            
        return _ok({"updated": int(updated), "from": start_iso, "to": end_iso, "granularity": g})
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

def query(type: str, from_utc: str, to_utc: str, granularity: str = "daily") -> Dict[str, Any]:
    """
    type: "orders" | "orders.paid" | "bookings" | "bookings.confirmed" | "reviews" | "reviews.published"
    Returns rollup buckets with counters filtered to the requested key(s).
    """
    try:
        g = (granularity or "").strip().lower()
        if g not in ROLLUP_BUCKETS:
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "granularity must be 'daily' or 'weekly'")
        dt_from = _parse_iso_utc(from_utc)
        dt_to = _parse_iso_utc(to_utc)
        if dt_to <= dt_from:
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "to_utc must be greater than from_utc")
        
        # Convert to bucket boundaries [start, end)
        sb = _bucket_str(_bucket_start(dt_from, g))
        eb = _bucket_str(_bucket_start(dt_to, g))   # exclusive
        keys = _keys_filter_from_query_type(type)

        try:
            items = repo_metrics.query_rollup(g, sb, eb, keys)
        except repo_metrics.RepoError as e:
            return _err(e.code, e.message)
        
        return _ok(
            {
                "items": items,
                "total": len(items),
                "from": sb,
                "to": eb,
                "granularity": g
            }
        )
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    