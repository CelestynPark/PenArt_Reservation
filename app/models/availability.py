from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

from app.models.base import TIMESTAMP_FIELDS
from app.utils.time import isoformat_utc, now_utc

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "normalize_availability",
]


collection_name = "availability"

schema_fields: Dict[str, Any] = {
    "rules": {
        "type": "array",
        "items": {
            "type": "object",
            "schema": {
                "dow": {"type": "array", "items": {"type": "int(0..6)"}},
                "start": {"type": "string", "format": "HH:MM"},
                "end": {"type": "string", "format": "HH:MM"},
                "break": {
                    "type": "array?",
                    "items": {
                        "type": "object",
                        "schema": {
                            "start": {"type": "string", "format": "HH:MM"},
                            "end": {"type": "string", "format": "HH:MM"},
                        },
                    },
                },
                "slot_min": {"type": "int", "min": 1},
                "services": {"type": "array?", "items": {"type": "string"}},
            },
        },
        "default": [],
    },
    "exceptions": {
        "type": "array",
        "items": {
            "type": "object",
            "schema": {
                "date": {"type": "string", "format": "YYYY-MM-DD"},
                "is_closed": {"type": "bool", "default": False},
                "blocks": {
                    "type": "array?",
                    "items": {
                        "type": "object",
                        "schema": {
                            "start": {"type": "string", "format": "HH:MM"},
                            "end": {"type": "string", "format": "HH:MM"},
                        },
                    },
                },
            },
        },
        "default": [],
    },
    "base_days": {"type": "array", "items": {"type": "int(0..6)"}},
    TIMESTAMP_FIELDS[0]: {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[1]: {"type": "string?", "format": "iso8601"},
}

indexes = [
    # Optional helper if rule-level service filtering becomes hot
    {"keys": [("rules.services", 1)], "options": {"name": "rules.services_1", "background": True}},
]


class AvailabilityPayloadError(ValueError):
    code = "ERR_INVALID_PAYLOAD"


def _ensure_mapping(doc: Mapping) -> None:
    if not isinstance(doc, Mapping):
        raise AvailabilityPayloadError("document must be a mapping/dict")


def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _norm_int(v: Any, field: str, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    try:
        iv = int(v)
    except Exception as e:
        raise AvailabilityPayloadError(f"{field} must be integer") from e
    if min_value is not None and iv < min_value:
        raise AvailabilityPayloadError(f"{field} must be ≥ {min_value}")
    if max_value is not None and iv > max_value:
        raise AvailabilityPayloadError(f"{field} must be ≤ {max_value}")
    return iv


def _norm_bool(v: Any) -> bool:
    return bool(v) if isinstance(v, bool) else False


def _norm_unique_sorted_ints(items: Iterable[Any], field: str, min_value: int, max_value: int) -> List[int]:
    seen = set()
    out: List[int] = []
    for x in items or []:
        iv = _norm_int(x, field, min_value=min_value, max_value=max_value)
        if iv not in seen:
            seen.add(iv)
            out.append(iv)
    out.sort()
    return out


@dataclass(frozen=True)
class _HM:
    h: int
    m: int

    def minutes(self) -> int:
        return self.h * 60 + self.m

    def __str__(self) -> str:
        return f"{self.h:02d}:{self.m:02d}"


def _parse_hhmm(s: Any, field: str) -> _HM:
    if not isinstance(s, str) or len(s) != 5 or s[2] != ":":
        raise AvailabilityPayloadError(f"{field} must be HH:MM")
    hh, mm = s[:2], s[3:]
    try:
        h = int(hh)
        m = int(mm)
    except Exception as e:
        raise AvailabilityPayloadError(f"{field} must be HH:MM") from e
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise AvailabilityPayloadError(f"{field} out of range")
    return _HM(h, m)


def _ensure_start_before_end(start: _HM, end: _HM, field_prefix: str) -> None:
    if start.minutes() >= end.minutes():
        raise AvailabilityPayloadError(f"{field_prefix}.start must be earlier than {field_prefix}.end")


def _norm_breaks(items: Iterable[Mapping[str, Any]] | None, field_prefix: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for i, b in enumerate(items or []):
        if not isinstance(b, Mapping):
            raise AvailabilityPayloadError(f"{field_prefix}[{i}] must be an object")
        s = _parse_hhmm(b.get("start"), f"{field_prefix}[{i}].start")
        e = _parse_hhmm(b.get("end"), f"{field_prefix}[{i}].end")
        _ensure_start_before_end(s, e, f"{field_prefix}[{i}]")
        out.append({"start": str(s), "end": str(e)})
    return out


def _unique_trimmed_strings(items: Iterable[Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items or []:
        if not isinstance(x, str):
            continue
        t = x.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _norm_rules(rules: Iterable[Mapping[str, Any]] | None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, r in enumerate(rules or []):
        if not isinstance(r, Mapping):
            raise AvailabilityPayloadError(f"rules[{idx}] must be an object")
        dow = _norm_unique_sorted_ints(r.get("dow") or [], f"rules[{idx}].dow", 0, 6)
        if not dow:
            raise AvailabilityPayloadError(f"rules[{idx}].dow must have at least one day")
        start = _parse_hhmm(r.get("start"), f"rules[{idx}].start")
        end = _parse_hhmm(r.get("end"), f"rules[{idx}].end")
        _ensure_start_before_end(start, end, f"rules[{idx}]")
        slot_min = _norm_int(r.get("slot_min"), f"rules[{idx}].slot_min", min_value=1)
        brks = _norm_breaks(r.get("break"), f"rules[{idx}].break")
        services = _unique_trimmed_strings(r.get("services") or [])
        out.append(
            {
                "dow": dow,
                "start": str(start),
                "end": str(end),
                "break": brks,
                "slot_min": slot_min,
                "services": services or None,
            }
        )
    return out


def _norm_blocks(blocks: Iterable[Mapping[str, Any]] | None, field_prefix: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for i, b in enumerate(blocks or []):
        if not isinstance(b, Mapping):
            raise AvailabilityPayloadError(f"{field_prefix}[{i}] must be an object")
        s = _parse_hhmm(b.get("start"), f"{field_prefix}[{i}].start")
        e = _parse_hhmm(b.get("end"), f"{field_prefix}[{i}].end")
        _ensure_start_before_end(s, e, f"{field_prefix}[{i}]")
        out.append({"start": str(s), "end": str(e)})
    return out


def _parse_yyyy_mm_dd(s: Any, field: str) -> str:
    if not isinstance(s, str) or len(s) != 10 or s[4] != "-" or s[7] != "-":
        raise AvailabilityPayloadError(f"{field} must be YYYY-MM-DD")
    y, m, d = s.split("-")
    try:
        yi = int(y)
        mi = int(m)
        di = int(d)
    except Exception as e:
        raise AvailabilityPayloadError(f"{field} must be YYYY-MM-DD") from e
    if yi < 1970 or not (1 <= mi <= 12) or not (1 <= di <= 31):
        raise AvailabilityPayloadError(f"{field} out of range")
    return f"{yi:04d}-{mi:02d}-{di:02d}"


def _norm_exceptions(ex: Iterable[Mapping[str, Any]] | None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for idx, e in enumerate(ex or []):
        if not isinstance(e, Mapping):
            raise AvailabilityPayloadError(f"exceptions[{idx}] must be an object")
        date = _parse_yyyy_mm_dd(e.get("date"), f"exceptions[{idx}].date")
        is_closed = _norm_bool(e.get("is_closed"))
        blocks = _norm_blocks(e.get("blocks"), f"exceptions[{idx}].blocks")
        out.append({"date": date, "is_closed": is_closed, "blocks": blocks or None})
    return out


def normalize_availability(doc: Mapping[str, Any]) -> Dict[str, Any]:
    _ensure_mapping(doc)
    src = deepcopy(dict(doc))
    out: MutableMapping[str, Any] = {}

    base_days = _norm_unique_sorted_ints(src.get("base_days") or [], "base_days", 0, 6)
    if not base_days:
        raise AvailabilityPayloadError("base_days must have at least one day")
    out["base_days"] = base_days

    out["rules"] = _norm_rules(src.get("rules"))
    out["exceptions"] = _norm_exceptions(src.get("exceptions"))

    now_iso = _now_iso()
    created = src.get(TIMESTAMP_FIELDS[0])
    updated = src.get(TIMESTAMP_FIELDS[1])
    out[TIMESTAMP_FIELDS[0]] = created if isinstance(created, str) and created else now_iso
    out[TIMESTAMP_FIELDS[1]] = updated if isinstance(updated, str) and updated else now_iso

    return dict(out)
