from __future__ import annotations

from typing import Any, Optional

from pymongo import ASCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.models.base import BaseModel
from app.utils.time import parse_kst_date

COLLECTION = "availability"

__all__ = ["COLLECTION", "get_collection", "ensure_indexes", "Availability"]


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("updated_at", ASCENDING)], name="idx_updated_at"),
        ]
    )


def _is_hhmm(v: Any) -> bool:
    if not isinstance(v, str) or len(v) != 5 or v[2] != ":":
        return False
    hh, mm = v[:2], v[3:]
    if not (hh.isdigit() and mm.isdigit()):
        return False
    h, m = int(hh), int(mm)
    return 0 <= h <= 23 and 0 <= m <= 59


def _hhmm_to_min(v: str) -> int:
    if not _is_hhmm(v):
        raise ValueError("invalid time format HH:MM")
    h, m = int(v[:2]), int(v[3:])
    return h * 60 + m


def _slot_min(v: Any) -> int:
    if isinstance(v, bool):
        raise ValueError("slot_min invalid")
    try:
        n = int(v)
    except Exception:
        raise ValueError("slot_min invalid")
    if n < 15 or n % 15 != 0:
        raise ValueError("slot_min must be >=15 and a multiple of 15")
    return n


def _norm_dow_list(v: Any) -> list[int]:
    if not isinstance(v, list) or not v:
        raise ValueError("dow must be non-empty list")
    out: list[int] = []
    for x in v:
        try:
            i = int(x)
        except Exception:
            raise ValueError("dow must be integers 0..6")
        if i < 0 or i > 6:
            raise ValueError("dow must be in 0..6")
        out.append(i)
    # keep order but remove exact duplicates while preserving first occurrence
    seen = set()
    dedup: list[int] = []
    for i in out:
        if i not in seen:
            dedup.append(i)
            seen.add(i)
    return dedup


def _norm_services(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("services must be list")
    out: list[str] = []
    for s in v:
        if not isinstance(s, str) or s.strip() == "":
            raise ValueError("service_id must be string")
        out.append(s.strip())
    return out


def _norm_breaks(v: Any, window_start_min: int, window_end_min: int) -> list[dict[str, str]]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("break must be list")
    out: list[dict[str, str]] = []
    for b in v:
        if not isinstance(b, dict):
            raise ValueError("break item must be object")
        s, e = b.get("start"), b.get("end")
        if not (_is_hhmm(s) and _is_hhmm(e)):
            raise ValueError("break time must be HH:MM")
        sm, em = _hhmm_to_min(s), _hhmm_to_min(e)
        if not (sm < em):
            raise ValueError("break start must be before end")
        if sm < window_start_min or em > window_end_min:
            raise ValueError("break must be within rule window")
        out.append({"start": f"{s[:2]}:{s[3:]}", "end": f"{e[:2]}:{e[3:]}"})
    return out


def _norm_blocks(v: Any) -> list[dict[str, str]]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("blocks must be list")
    out: list[dict[str, str]] = []
    for b in v:
        if not isinstance(b, dict):
            raise ValueError("block item must be object")
        s, e = b.get("start"), b.get("end")
        if not (_is_hhmm(s) and _is_hhmm(e)):
            raise ValueError("block time must be HH:MM")
        sm, em = _hhmm_to_min(s), _hhmm_to_min(e)
        if not (sm < em):
            raise ValueError("block start must be before end")
        out.append({"start": f"{s[:2]}:{s[3:]}", "end": f"{e[:2]}:{e[3:]}"})
    return out


def _norm_rule(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("rule must be object")
    dow = _norm_dow_list(v.get("dow"))
    start, end = v.get("start"), v.get("end")
    if not (_is_hhmm(start) and _is_hhmm(end)):
        raise ValueError("rule time must be HH:MM")
    sm, em = _hhmm_to_min(start), _hhmm_to_min(end)
    if not (sm < em):
        raise ValueError("rule start must be before end")
    slot = _slot_min(v.get("slot_min"))
    brks = _norm_breaks(v.get("break"), sm, em)
    services = _norm_services(v.get("services"))
    return {
        "dow": dow,
        "start": f"{start[:2]}:{start[3:]}",
        "end": f"{end[:2]}:{end[3:]}",
        "break": brks,
        "slot_min": slot,
        "services": services if services else None,
    }


def _norm_exception(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("exception must be object")
    date_raw = v.get("date")
    if not isinstance(date_raw, str):
        raise ValueError("exception.date must be string")
    d = parse_kst_date(date_raw)
    date_norm = d.strftime("%Y-%m-%d")
    is_closed = bool(v.get("is_closed", False))
    blocks = _norm_blocks(v.get("blocks"))
    return {"date": date_norm, "is_closed": is_closed, "blocks": blocks}


class Availability(BaseModel):
    def __init__(self, doc: Optional[dict[str, Any]] = None):
        super().__init__(doc or {})

    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        doc: dict[str, Any] = {}

        rules_in = payload.get("rules") or []
        if not isinstance(rules_in, list):
            raise ValueError("rules must be list")
        rules_out = [_norm_rule(r) for r in rules_in]

        exc_in = payload.get("exceptions") or []
        if not isinstance(exc_in, list):
            raise ValueError("exceptions must be list")
        exc_out = [_norm_exception(e) for e in exc_in]

        base_days_in = payload.get("base_days") or []
        if not isinstance(base_days_in, list):
            raise ValueError("base_days must be list")
        base_days: list[int] = []
        seen = set()
        for x in base_days_in:
            try:
                i = int(x)
            except Exception:
                raise ValueError("base_days must be integers 0..6")
            if i < 0 or i > 6:
                raise ValueError("base_days must be in 0..6")
            if i not in seen:
                base_days.append(i)
                seen.add(i)

        doc["rules"] = rules_out
        doc["exceptions"] = exc_out
        doc["base_days"] = base_days

        return Availability.stamp_new(doc)

    @staticmethod
    def prepare_update(partial: dict[str, Any]) -> dict[str, Any]:
        upd: dict[str, Any] = {}

        if "rules" in partial:
            rules_in = partial.get("rules")
            if not isinstance(rules_in, list):
                raise ValueError("rules must be list")
            upd["rules"] = [_norm_rule(r) for r in rules_in]

        if "exceptions" in partial:
            exc_in = partial.get("exceptions")
            if not isinstance(exc_in, list):
                raise ValueError("exceptions must be list")
            upd["exceptions"] = [_norm_exception(e) for e in exc_in]

        if "base_days" in partial:
            base_days_in = partial.get("base_days")
            if not isinstance(base_days_in, list):
                raise ValueError("base_days must be list")
            base_days: list[int] = []
            seen = set()
            for x in base_days_in:
                try:
                    i = int(x)
                except Exception:
                    raise ValueError("base_days must be integers 0..6")
                if i < 0 or i > 6:
                    raise ValueError("base_days must be in 0..6")
                if i not in seen:
                    base_days.append(i)
                    seen.add(i)
            upd["base_days"] = base_days

        return Availability.stamp_update(upd)
