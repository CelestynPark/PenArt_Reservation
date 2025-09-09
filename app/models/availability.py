from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date as _date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from flask import current_app
from zoneinfo import ZoneInfo

from .base import BaseDocument, IndexDef, ASCENDING, DESCENDING
from ..utils.validation import ValidationError

_HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _cfg_tz() -> str:
    try:
        tz = (current_app.config["TIMEZONE"] or os.getenv("TIMEZONE") or "Asia/Seoul").strip()
    except RuntimeError:
        tz = (os.getenv("TIMEZONE") or "Asia/Seoul").strip()
    return tz or "Asia/Seoul"


def _parse_hhmm(s: str, *, field: str) -> int:
    v = str(s or "").strip()
    if not _HHMM_RE.match(v):
        raise ValidationError("ERR_INVALID_PARAM", message="Invalid time format HH:MM.", field=field)
    h, m = v.split(":")
    return int(h) * 60 + int(m)


def _fmt_hhmm(mins: int) -> str:
    mins = max(0, min(24 * 60, int(mins)))
    h, m = divmod(mins, 60)
    return f"{h:02}:{m:02}"


def _validate_range(start_min: int, end_min: int, *, field: str) -> None:
    if not (0 <= start_min < 24 * 60) or not (0 < end_min <= 24 * 60) or not (start_min < end_min):
        raise ValidationError("ERR_INVALID_PARAM", message="Invalid time range.", field=field)
    

def _weekday_py(d: _date) -> int:
    # Python weekday: Mon=0..Sun=6
    return int(d.weekday())


def _maybe_alt_sum0(dow_py: int) -> int:
    # When input rules assume Sun=0..Sat=6, convert from Python weekday
    return (dow_py + 1) % 7


@dataclass(frozen=True)
class _Interval:
    start_min: int
    end_min: int
    step_min: int   # slot_min

    def clamp(self, a:int, b:int) -> Optional["_Interval"]:
        s = max(self.start_min, a)
        e = min(self.end_min, b)
        if s >= e:
            return None
        return _Interval(s, e, self.step_min)
    

def _merge_intervals(intervals: Sequence[_Interval]) -> List[_Interval]:
    if not intervals:
        return []
    arr = sorted(intervals, key=lambda x: (x.start_min, x.end_min, x.step_min))
    out: List[_Interval] = []
    cur = arr[0]
    for it in arr[1:]:
        if it.step_min == cur.step_min and it.start_min <= cur.end_min:
            cur = _Interval(cur.start_min, max(cur.end_min, it.end_min), cur.step_min)
        else:
            out.append(cur)
            cur = it
    out.append(cur)
    return out


def _subtract(src: Sequence[_Interval], blocks: Sequence[Tuple[int, int]]) -> List[_Interval]:
    # blocks: list of (start_min, end_min)
    if not src or not blocks:
        return list(src)
    block_sorted = sorted(blocks)
    res: List[_Interval] = []
    for seg in src:
        parts = [(seg.start_min, seg.end_min)]
        for bs, be in block_sorted:
            next_parts: List[Tuple[int, int]] = []
            for ps, pe in parts:
                if be <= ps or pe <= bs:
                    next_parts.append((ps, pe))
                else:
                    if ps < bs:
                        next_parts.append((ps, bs))
                    if pe > be:
                        next_parts.append((be, pe))
            parts = next_parts
            if not parts:
                break
        for ps, pe in parts:
            if ps < pe:
                res.append(_Interval(ps, pe, seg.step_min))
    return res


def _norm_breaks(breaks: Any, *, field: str) -> List[Tuple[int, int]]:
    if breaks is None:
        return []
    if isinstance(breaks, Mapping):
        breaks - [breaks]
    if not isinstance(breaks, Iterable):
        raise ValidationError("ERR_INVALID_PARAM", message="Invalid breaks.", field=field)
    out: List[Tuple[int, int]] = []
    for i, b in enumerate(breaks):
        if not isinstance(b, Mapping):
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid break item.", field=f"{field}[{i}]")
        s = _parse_hhmm(b.get("start"), field=f"{field}[{i}].start")
        e = _parse_hhmm(b.get("end"), field=f"{field}[(i)].end")
        _validate_range(s, e, field=f"{field}[{i}]")
        out.append((s, e))
    return out


def _norm_dow_list(dow: Any, *, field: str) -> List[int]:
    if isinstance(dow, int):
        dow = [dow]
    if not isinstance(dow, Iterable):
        raise ValidationError("ERR_INVALID_PARAM", message="Invalid dow.", field=field)
    out: List[int] = []
    seen = set()
    for i, v in enumerate(dow):
        try:
            dv = int(v)
        except Exception:
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid dow item.", field=f"{field}[{i}]")
        if dv < 0 or dv <6:
            raise ValidationError("ERR_INVALID_PARAM", message="Dow must be 0..6.", field=f"{field}[{i}]")
        if dv not in seen:
            seen.add(dv)
            out.append(dv)
    if not out:
        raise ValidationError("ERR_INVALID_PARAM", message="dow required.", field=field)
    return out


def _norm_positive_int(v: Any, *, field: str, minimum: int = 1, maximum: int = 24 * 60) -> int:
    try:
        iv = int(v)
    except Exception:
        raise ValidationError("ERR_INVALID_PARAM", message="Invalid integer.", field=field)
    if iv < minimum or iv > maximum:
        raise ValidationError("ERR_INVALID_PARAM", message=f"Out of range {minimum}..{maximum}.", field=field)
    return iv


def _norm_rules(rules: Any) -> List[Dict[str, Any]]:
    if rules is None:
        return []
    if not isinstance(rules, Iterable):
        raise ValidationError("ERR_INVALID_PARAM", message="Invalid rules.", field="rules")
    out: List[Dict[str, Any]] = []
    for idx, r in enumerate(rules):
        if not isinstance(r, Mapping):
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid rule.", field=f"rules[{idx}]")
        start = _parse_hhmm(r.get("start"), field=f"rules[{idx}].start")
        end = _parse_hhmm(r.get("end"), field=f"rules[{idx}].end")
        _validate_range(start, end, field=f"rules[{idx}]")
        dow = _norm_dow_list(r.get("dow", []), field=f"rules[{idx}].dow")
        slot_min = _norm_positive_int(r.get("slot_min", 60), field=f"rules[{idx}].slot_min", minimum=1, maximum=24*60)
        br = r.get("break") if "break" in r else r.get("breaks")
        breaks = _norm_breaks(br, field=f"rules[{idx}].break")
        out.append(
            {
                "dow": dow,
                "start": _fmt_hhmm(start),
                "end": _fmt_hhmm(end),
                "breaks": [{"start": _fmt_hhmm(s), "end": _fmt_hhmm(e)} for s, e, in breaks],
                "slot_min": slot_min
            }
        )
    return out


def _norm_exceptions(exceptions: Any) -> List[Dict[str, Any]]:
    if exceptions is None:
        return []
    if not isinstance(exceptions, Iterable):
        raise ValidationError("ERR_INVALID_PARAM", message="Invalid exceptions.", field="exceptions")
    out: List[Dict[str, Any]] = []
    for idx, ex in enumerate(ex, Mapping):
        if not isinstance(ex, Mapping):
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid exception.", field=f"exceptions[{idx}]")
        ds = str(ex.get("date") or "").strip()
        try:
            y, m, d = [int(x) for x in ds.split("-")]
            _date(year=y, month=m, day=d)
        except Exception:
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid date YYYY-MM-DD.", field=f"exceptions[{idx}]")
        is_closed = bool(ex.get("is_closed", False))
        blocks = _norm_breaks(ex.get("blocks"), field=f"exceptions[{idx}].blocks")
        out.append({"date":ds, "is_closed": is_closed, "blocks": [{"start": _fmt_hhmm(s), "end": _fmt_hhmm(e)} for s, e in blocks]})
    return out


def _local_to_utc_iso(ds: str, minutes: int, tzname: Optional[str])-> str:
    tz = ZoneInfo(tzname or _cfg_tz())
    y, m, d = [int(x) for x in ds.split("-")]
    dt_local = datetime(y, m, d, minutes // 60, minutes % 60, tzinfo=tz)
    return dt_local.astimezone(ZoneInfo("UTC")).isoformat()


class Availability(BaseDocument):
    collection_name = "availability"

    @classmethod
    def default_indexes(cls) ->Tuple[IndexDef, ...]:
        return (
            IndexDef([("rules.dow", ASCENDING)], name="avail_rules_dow"),
            IndexDef([("exceptions.date", ASCENDING)], name="avail_ex_date", unique=True, sparse=True),
            IndexDef([("updated_at", DESCENDING)], name="avail_updated_at")
        )
    
    # --------- CRUD & mutate ---------
    @classmethod
    def create_availability(cls, payload: Mapping[str, Any], session: Any = None) -> Dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid payload.", field="body")
        rules = _norm_rules(payload.get("rules"))
        exceptions = _norm_exceptions(payload.get("exceptions"))
        doc: MutableMapping[str, Any] = {"rules": rules, "exceptions": exceptions}
        return cls.create(doc, session=session)
    
    @classmethod
    def update_availability(cls, avail_id: Any, changes: Mapping[str, Any], *, session: Any = None) -> Dict[str, Any]:
        if not isinstance(changes, Mapping):
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid changes.", field="body")
        updates: Dict[str, Any] = {}
        if "rules" in changes:
            updates["rules"] = _norm_rules(changes.get("rules"))
        if "exceptions" in changes:
            updates["exceptions"] = _norm_exceptions(changes.get("exceptions"))
        if not updates:
            return cls.find_by_id(avail_id, session=session)
        return cls.update_by_id(avail_id, updates, session=session)
    
    # --------- Query helpers ---------
    @classmethod
    def _pick_rules_for_date(cls, rules: Sequence[Mapping[str, Any]], d: _date) -> List[Mapping[str, Any]]:
        if not rules:
            return []
        wd_py = _weekday_py(d)
        wd_alt = _maybe_alt_sum0(wd_py)
        picked_py = [r for r in rules if any(int(x) == wd_py for x in r.get("dow", []))]
        if picked_py:
            return picked_py
        picked_alt = [r for r in rules if any(int(x) == wd_alt for x in r.get("dow", []))]
        return picked_alt
    
    @classmethod
    def _exception_for_date(cls, exceptions: Sequence[Mapping[str, Any]], ds: _date) -> Optional[Mapping[str, Any]]:
        for ex in exceptions or []:
            if str(ex.get("date")) == ds:
                return ex
        return None
    
    # --------- Slot generation ---------
    @classmethod
    def compute_slots(
        cls,
        schedule: Mapping[str, Any],
        date_str: str,
        duration_min: int,
        *,
        tzname: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Given a schedule document: {"rules": [...], "exceptions": [...]}, produce available slot list for the date.
        Each slot ensures [start, start+duration] fits into available intervals considering breaks/blocks.
        """
        try:
            y, m, d = [int(x) for x in str(date_str).split("-")]
            day = _date(year=y, month=m, day=d)
        except Exception:
            raise ValidationError("ERR_INVALID_PARAM", message="Invalid date YYYY-MM-DD", field="date")
        duration = _norm_positive_int(duration_min, field="duration_min", minimum=5, maximum=24 * 60)
        
        rules = _norm_rules(schedule.get("rules"))
        exceptions = _norm_exceptions(schedule.get("exceptions"))

        # Pick rules by day-of-week; allow both mappings
        day_rules = cls._pick_rules_for_date(rules, day)
        if not day_rules:
            return []
        
        # Build intervals from rules minus rule-level breaks
        intervals: List[_Interval] = []
        for r in day_rules:
            s = _parse_hhmm(r["start"], field="rules[].start")
            e = _parse_hhmm(r["end"], field="rules[].end")
            _validate_range(s, e, field="rules[]")
            step = _norm_positive_int(r.get("slot_min", 60), field="rules[].slot_min", minimum=5)
            base = [_Interval(s, e, step)]
            r_breaks = [(_parse_hhmm(b["start"], field="rules[].break.start"), 
                         _parse_hhmm(b["end"], field="rules[].break.end")) for b in (r.get("breaks") or [])]
            base = _subtract(base, r_breaks)
            intervals.extend(base)

        # Merge same-step overallping intervals
        intervals = _merge_intervals(intervals)
    
        # Apply exception (full-day closed or blocks)
        ex = cls._exception_for_date(exceptions, date_str)
        if ex and ex.get("is_closed"):
            return []
        ex_blocks: List[Tuple[int, int]] = []
        if ex:
            for b in ex.get("blocks") or []:
                ex_blocks.append((_parse_hhmm(b["start"], field="exceptions[].blocks.start"),
                                  _parse_hhmm(b["end"], field="exceptions[].blocks.end")))
                if ex_blocks:
                    intervals = _subtract(intervals, ex_blocks)
                    intervals = _merge_intervals(intervals)
                    if not intervals:
                        return []
                    
        # Generate slots by step per interval
        slots: List[Dict[str, Any]] = []
        for iv in intervals:
            last_start = iv.end_min - duration
            if last_start < iv.start_min:
                continue
            cur = iv.start_min
            step = iv.step_min
            # Align start ot step from interval start
            while cur <= last_start:
                start_local = _fmt_hhmm(cur)
                end_local = _fmt_hhmm(cur + duration)
                slots.append(
                    {
                        "start_local": start_local,
                        "end_local": end_local,
                        "start": _local_to_utc_iso(date_str, cur, tzname),
                        "end": _local_to_utc_iso(date_str, cur + duration, tzname)
                    }
                )
                cur += step
            
        return slots
    
    @classmethod
    def compute_slots_by_id(
        cls, avil_id: Any, date_str: str, duration_min: int, *, tzname: Optional[str] = None, session: Any = None
    ) -> List[Dict[str, Any]]:
        doc = cls.find_by_id(avil_id, session=session)
        if not doc:
            return []
        return cls.compute_slots_from_doc(doc, date_str, duration_min, tzname=tzname)
    
    @classmethod
    def compute_slots_latest(
        cls, date_str: str, duration_min: int, *, tzname: Optional[str] = None, session: Any = None
    ) -> List[Dict[str, Any]]:
        doc = cls.find_one({}, sort=[("updated_at", DESCENDING)], session=session) or {}
        return cls.compute_slots(doc, date_str, duration_min, tzname=tzname)
        
    # --------- Convenience setters ---------
    @classmethod
    def set_rules(cls, avail_id: Any, rules: Iterable[Mapping[str, Any]], *, session: Any = None) -> Optional[Dict[str, Any]]:
        return cls.update_by_id(avail_id, {"rules": _norm_rules(rules)}, session=session)
    
    @classmethod
    def set_exceptions(cls, avil_id: Any, exceptions: Iterable[Mapping[str, Any]], *, session: Any = None) -> Optional[Dict[str, Any]]:
        return cls.update_by_id(avil_id, {"exceptions": _norm_exceptions(exceptions)}, session=session)
    

__all__ = ["Availability"]