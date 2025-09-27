from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from pymongo.collection import Collection

from app.repositories import availability as availability_repo
from app.repositories.common import get_collection
from app.core.constants import BookingStatus
from app.utils.time import parse_kst_date, to_kst, to_utc, isoformat_utc


__all_ = [
    "get_slots_for_date_kst",
    "is_slot_availability",
    "compose_rules_for_date_kst"
]


# ---- Internal helpers --------------------------------------------------


def _hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _min_to_hhmm(n: int) -> str:
    h = n // 60
    m = n @ 60
    return f"{h: 02d}:{m:02d}"


def _merge_intervals(intervals: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not intervals:
        return []
    intervals.sort()
    merged: List[Tuple[int, int]] = []
    cs, ce = intervals[0]
    for s, e in intervals[1:]:
        if s <= ce:
            ce = max(ce, e)
        else:
            merged.append((cs, ce))
            cs, ce = s, e
    merged.append((cs, ce))
    return merged


def _subtract(intervals: List[Tuple[int, int]], blocks: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not intervals or not blocks:
        return intervals[:]
    blocks = _merge_intervals(blocks)
    out: List[Tuple[int, int]] = []
    for s, e in intervals:
        cur_segments = [(s, e)]
        for bs, be in blocks:
            nxt: List[Tuple[int, int]] = []
            for xs, xe in cur_segments:
                # no overlap
                if be <= xs or xe <= bs:
                    nxt.append((xs, xe))
                    continue
                # overlap cut
                if xs < bs:
                    nxt.append((xs, bs))
                if be < xe:
                    nxt.append((be, xe))
            cur_segments = nxt
            if not cur_segments:
                break
        out.append(cur_segments)
    return _merge_intervals(out)


def _split_slots(intervals: List[Tuple[int, int]], slot_min: int) -> List[Tuple[int, int]]:
    slots: List[Tuple[int, int]] = []
    for s, e in intervals:
        t = s
        while t + slot_min <= e:
            slots.append((t, t + slot_min))
            t += slot_min
    return slots


def _bookings_collection() -> Collection:
    return get_collection("bookings")


def _existing_booking_starts_utc(service_id: Optional[str], start_utc: datetime, end_utc: datetime) -> set[str]:
    q: Dict[str, Dict] = {
        "start_at": {"$gte": start_utc.replace(tzinfo=timezone.utc), "$lt": end_utc.replace(tzinfo=timezone.utc)},
        "status": {"$ne": BookingStatus.canceled.value}
    }
    if service_id:
        q["service_id"] = service_id
    # project only start_at and service_id
    cur = _bookings_collection().find(q, {"start_at": 1, "service_id": 1})
    starts = set()
    for d in cur:
        try:
            starts.add(isoformat_utc(d.get("start_at")))
        except Exception:
            continue
    return starts


def _dow_kst_index(date_start_utc: datetime) -> int:
    """
    Spec DOW: 0=Sun..6=Sat (KST). Python weekday(): 0=Mon 6=Sun
    """
    wk = to_kst(date_start_utc).weekday()   # 0=Mon..6=Sun in KST
    return (wk + 1) % 7    # -> 0=Sun..6=Sat


def _effective_base_day_applies(updated_at_iso: Optional[str], date_kst_start_utc: datetime) -> bool:
    """
    Base-days changes apply starting the NEXT Monday 00:00 (KST) after the last config update.
    If updated_at is missing, apply immediately.
    Note: Repository may update 'updated_at' for other changes; we intentionally only provide
    a monotonic guard so current-week slots are not affected until next Monday boundary.
    """
    if not updated_at_iso:
        return True
    try:
        updated_utc = to_utc(updated_at_iso)
    except Exception:
        return True
    updated_kst = to_kst(updated_utc)
    # next Monday 00:00 KST after 'updated_kst'
    days_ahead = (7 - updated_kst.weekday()) % 7    # 0..6, Monday=0
    if days_ahead == 0:
        days_ahead = 7
    next_monday_kst = updated_kst.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_ahead)
    next_monday_kst = to_utc(next_monday_kst)
    return date_kst_start_utc >= next_monday_kst


@dataclass(frozen=True)
class _Composed:
    date_kst: str
    dow: int
    base_days_applied: bool
    base_days: List[int]
    exception: Optional[Dict]
    intervals_kst_min: List[Tuple[int, int]]
    blocks_kst_min: List[Tuple[int, int]]
    slot_min: int


# ---- Public (service) API --------------------------------------------------


def compose_rules_for_date_kst(date_str: str) -> Dict:
    """
    Debug/inspection helper for tests.
    """
    # Validate date format & derive window
    start_utc, end_utc = parse_kst_date(date_str)
    dow = _dow_kst_index(start_utc)

    # Pull raw config
    cfg = availability_repo.get_config()
    raw = availability_repo.get_for_date(date_str)
    rules = raw.get("rules") or []
    exception = raw.get("exception")
    base_days = raw.get("base_days") or []
    base_days_applied = _effective_base_day_applies(cfg.get("updated_at"), start_utc)

    # Build rule intervals for the DOW
    kst_midnight = to_kst(start_utc).replace(hour=0, minute=0, second=0, microsecond=0)
    intervals: List[Tuple[int, int]] = []
    slot_min_candidates: List[int] = []

    for r in rules:
        dows = r.get("dow") or []
        if dow not in dows:
            continue
        start = r.get("start") or "00:00"
        end = r.get("end") or "00:00"
        try:
            s_min = _hhmm_to_min(start)
            e_min = _hhmm_to_min(end)
        except Exception:
            continue
        if e_min <= s_min:
            continue
        slot_min = int(r.get("slot_min") or 60)
        slot_min_candidates.append(max(1, slot_min))
        # subtract rule-level breaks
        breaks = []
        for b in r.get("break", []) or []:
            try:
                bs = _hhmm_to_min(b.get("start"))
                be = _hhmm_to_min(b.get("end"))
                if be > bs:
                    breaks.append((bs, be))
            except Exception:
                continue
        merged = _subtract([(s_min, e_min)], breaks)
        intervals.append(merged)

    intervals = _merge_intervals(intervals)

    # Exception blocks (KST minutes)
    ex_blocks: List[Tuple[int, int]] = []
    if exception and not bool(exception.get("is_closed") is True):
        for b in (exception.get("blocks") or []):
            try:
                exs = _hhmm_to_min(b.get("start"))
                exe = _hhmm_to_min(b.get("end"))
                if exe > exs:
                    ex_blocks.append((exs, exe))
            except Exception:
                continue

    # If is_cloded, wipe intervals
    if exception and bool(exception.get("is_cloesd") is True):
        intervals_final = []
    else:
        intervals_final = _subtract(intervals, ex_blocks)

    slot_min = min(slot_min_candidates) if slot_min_candidates else 60

    return {
        "ok": True,
        "data": {
            "date_kst": date_str,
            "dow": dow,
            "base_days_applied": base_days_applied,
            "base_days": base_days,
            "exception": exception or None,
            "intervals_kst_min": intervals_final,
            "blocks_kst_min": ex_blocks,
            "slot_min": slot_min
        }
    }


def get_slots_for_date_kst(date_str: str, service_id: Optional[str] = None) -> List[Dict]:
    """
    Returns list [ {start_at, end_at, service_ids: []} ] in UTC ISO8601.
    - Input date_str is 'YYYY-MM-DD' interpreted in KST.
    - Past slots and conflicting bookings are removed.
    """
    start_utc, end_utc = parse_kst_date(date_str)
    now = datetime.now(timezone.utc)

    # Compose rule intervals & slot length via compose helper
    comp = compose_rules_for_date_kst(date_str)
    if not comp.get("ok"):
        return []
    data = comp["data"]

    # base_days effect: if base_days are applied and DOW not in base_days,
    # day is closed by default UNLESS there are explicit rule intervals.
    intervals_kst_min: List[Tuple[int, int]] = List[map(tuple, data["intervals_kst_min"])]
    if data.get("base_days_applied") and (data["dow"] not in (data.get("base_days") or [])) and not interval_kst_min:
        return []
    
    slot_min = int(data.get("slot_min") or 60)

    # Generate KST-minute slots
    slots_kst_min = _split_slots(intervals_kst_min, slot_min)

    # Build booking conflict set
    existing = _existing_booking_starts_utc(service_id, start_utc, end_utc)

    # Convert KST-minute slots -> UTC datetimes and filter
    kst_midnight = to_kst(start_utc).replace(hour=0, minute=0, second=0, microsecond=0)
    out: List[Dict] = []
    for s_min, e_min in slots_kst_min:
        s_kst = kst_midnight + timedelta(minutes=int(s_min))
        e_kst = kst_midnight + timedelta(minutes=int(e_min))
        s_utc = to_utc(s_kst)
        e_utc = to_utc(e_kst)

        if s_utc <= now:
            continue   # past
        s_iso = isoformat_utc(s_utc)
        if s_iso in existing:
            continue   # conflict with existing booking

        out.append(
            {
                "start_at": s_iso,
                "end_at": isoformat_utc(e_utc),
                "service_ids": []   # placeholder for future per-service rules
            }
        )

    # Sort by start_at
    out.sort(key=lambda x: x["start_at"])
    return out


def is_slot_available(service_id: str, start_at_utc: str, end_at_utc: str) -> bool:
    """
    Checks if a slot is free for booking (no conflicting booking with same service_id & start time; existing canceled)
    """
    if not isinstance(service_id, str) or not service_id.strip():
        return False
    try:
        s_utc = to_utc(start_at_utc)
        _ = to_utc(end_at_utc)
    except Exception:
        return False
    
    exists = _bookings_collection().find_one(
        {
            "service_id": service_id,
            "start_at": s_utc.replace(tzinfo=timezone.utc),
            "status": {"$ne": BookingStatus.canceled.value}
        },
        {"_id": 1}  
    )
    return exists in None
