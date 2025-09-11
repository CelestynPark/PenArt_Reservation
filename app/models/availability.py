from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId

from app.models.base import BaseModel, _coerce_dt, _coerce_id

_HHMM_RE = re.compile(r"^([0-2]\d):([0-5]\d)$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_hhmm(s: Any, *, field: str) -> int:
    if not isinstance(s, str):
        raise ValueError(f"{field} must be 'HH:MM'")
    m = _HHMM_RE.fullmatch(s.strip())
    if not m:
        raise ValueError(f"{field} must match HH:MM")
    h, mm = int(m.group(1)), int(m.group(2))
    if h > 24:
        raise ValueError(f"{field} hour out of range")
    if h == 24 and mm != 0:
        raise ValueError(f"{field} minute must be 00 when hour is 24")
    total = h * 60 + mm
    if total > 24 * 60:
        raise ValueError(f"{field} out of day range")
    return total


def _minutes_to_hhmm(total: int) -> str:
    h = total // 60
    m = total % 60
    return f"{h:02d}:{m:02d}"


def _ensure_range(start_min: int, end_min: int, *, field_prefix: str, allow_equal: bool = False) -> None:
    if start_min > end_min or (not allow_equal and start_min == end_min):
        raise ValueError(f"{field_prefix}: start must be < end")


def _validate_non_overlapping(ranges: List[Tuple[int, int]], *, field: str) -> None:
    ranges_sorted = sorted(ranges, key=lambda x: x[0])
    prev_end = -1
    for s, e in ranges_sorted:
        if s < prev_end:
            raise ValueError(f"{field} has overlapping intervals")
        prev_end = e


def _ensure_int_in(v: Any, name: str, lo: int, hi: int) -> int:
    try:
        i = int(v)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"{name} must be an integer") from e
    if i < lo or i > hi:
        raise ValueError(f"{name} must be in [{lo}..{hi}]")
    return i


def _ensure_slot_min(v: Any) -> int:
    i = _ensure_int_in(v, "slot_min", 1, 24 * 60)
    if i < 15 or (i % 5) != 0:
        raise ValueError("slot_min must be >=15 and a multiple of 5")
    return i


def _clean_dows(values: Any, *, field: str) -> List[int]:
    if not isinstance(values, list):
        raise ValueError(f"{field} must be a list")
    out: List[int] = []
    seen = set()
    for v in values:
        i = _ensure_int_in(v, f"{field}[]", 0, 6)
        if i not in seen:
            out.append(i)
            seen.add(i)
    return out


def _clean_services(values: Any) -> List[ObjectId]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("services must be a list")
    out: List[ObjectId] = []
    for v in values:
        oid = _coerce_id(v)
        if oid is None:
            raise ValueError("services[] must be ObjectId or hex string")
        out.append(oid)
    return out


def _clean_rule(rule: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(rule, dict):
        raise ValueError("rule must be an object")
    dows = _clean_dows(rule.get("dow", []), field="rule.dow")
    if not dows:
        raise ValueError("rule.dow must not be empty")
    start_min = _parse_hhmm(rule.get("start"), field="rule.start")
    end_min = _parse_hhmm(rule.get("end"), field="rule.end")
    _ensure_range(start_min, end_min, field_prefix="rule.time")
    slot_min = _ensure_slot_min(rule.get("slot_min"))
    brk = rule.get("break") or []
    if not isinstance(brk, list):
        raise ValueError("rule.break must be a list")
    brk_ranges: List[Tuple[int, int]] = []
    cleaned_break: List[Dict[str, str]] = []
    for idx, item in enumerate(brk):
        if not isinstance(item, dict):
            raise ValueError("rule.break[] must be objects")
        bs = _parse_hhmm(item.get("start"), field=f"rule.break[{idx}].start")
        be = _parse_hhmm(item.get("end"), field=f"rule.break[{idx}].end")
        _ensure_range(bs, be, field_prefix=f"rule.break[{idx}]")
        if bs < start_min or be > end_min:
            raise ValueError("rule.break[] must lie within rule start/end")
        brk_ranges.append((bs, be))
        cleaned_break.append({"start": _minutes_to_hhmm(bs), "end": _minutes_to_hhmm(be)})
    _validate_non_overlapping(brk_ranges, field="rule.break")
    services = _clean_services(rule.get("services"))
    return {
        "dow": dows,
        "start": _minutes_to_hhmm(start_min),
        "end": _minutes_to_hhmm(end_min),
        "break": cleaned_break,
        "slot_min": slot_min,
        "services": services,
    }


def _clean_exception(exc: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(exc, dict):
        raise ValueError("exception must be an object")
    date = exc.get("date")
    if not isinstance(date, str) or not _DATE_RE.fullmatch(date):
        raise ValueError("exception.date must be YYYY-MM-DD")
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except Exception as e:  # noqa: BLE001
        raise ValueError("exception.date invalid") from e
    is_closed = bool(exc.get("is_closed", False))
    blocks = exc.get("blocks") or []
    if not isinstance(blocks, list):
        raise ValueError("exception.blocks must be a list")
    blk_ranges: List[Tuple[int, int]] = []
    cleaned_blocks: List[Dict[str, str]] = []
    for idx, item in enumerate(blocks):
        if not isinstance(item, dict):
            raise ValueError("exception.blocks[] must be objects")
        bs = _parse_hhmm(item.get("start"), field=f"exception.blocks[{idx}].start")
        be = _parse_hhmm(item.get("end"), field=f"exception.blocks[{idx}].end")
        _ensure_range(bs, be, field_prefix=f"exception.blocks[{idx}]")
        if bs < 0 or be > 24 * 60:
            raise ValueError("exception.blocks[] must lie within a day")
        blk_ranges.append((bs, be))
        cleaned_blocks.append({"start": _minutes_to_hhmm(bs), "end": _minutes_to_hhmm(be)})
    _validate_non_overlapping(blk_ranges, field="exception.blocks")
    return {"date": date, "is_closed": is_closed, "blocks": cleaned_blocks}


class Availability(BaseModel):
    __collection__ = "availability"

    rules: List[Dict[str, Any]]
    exceptions: List[Dict[str, Any]]
    base_days: List[int]

    def __init__(
        self,
        *,
        id: ObjectId | str | None = None,
        rules: List[Dict[str, Any]] | None = None,
        exceptions: List[Dict[str, Any]] | None = None,
        base_days: List[int] | None = None,
        created_at: Any | None = None,
        updated_at: Any | None = None,
    ) -> None:
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.rules = [ _clean_rule(r) for r in (rules or []) ]
        self.exceptions = [ _clean_exception(e) for e in (exceptions or []) ]
        self.base_days = _clean_dows(base_days or [], field="base_days")

    def to_dict(self, exclude_none: bool = True) -> Dict[str, Any]:
        base = super().to_dict(exclude_none=exclude_none)

        def _serialize_rule(r: Dict[str, Any]) -> Dict[str, Any]:
            services = r.get("services") or []
            svc_out = [str(s) if isinstance(s, ObjectId) else str(s) for s in services]
            return {
                "dow": list(r["dow"]),
                "start": r["start"],
                "end": r["end"],
                "break": list(r["break"]),
                "slot_min": r["slot_min"],
                "services": svc_out if services else [],
            }

        out: Dict[str, Any] = {
            **base,
            "rules": [_serialize_rule(r) for r in self.rules],
            "exceptions": [dict(e) for e in self.exceptions],
            "base_days": list(self.base_days),
        }
        if exclude_none:
            out = {k: v for k, v in out.items() if v is not None}
        return out

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Availability":
        obj: "Availability" = cls.__new__(cls)  # type: ignore[call-arg]
        setattr(obj, "id", _coerce_id(d.get("_id", d.get("id"))))
        setattr(obj, "created_at", _coerce_dt(d.get("created_at")))
        setattr(obj, "updated_at", _coerce_dt(d.get("updated_at"), getattr(obj, "created_at")))
        rules = d.get("rules") or []
        exceptions = d.get("exceptions") or []
        base_days = d.get("base_days") or []
        setattr(obj, "rules", [_clean_rule(r) for r in rules])
        setattr(obj, "exceptions", [_clean_exception(e) for e in exceptions])
        setattr(obj, "base_days", _clean_dows(base_days, field="base_days"))
        return obj
