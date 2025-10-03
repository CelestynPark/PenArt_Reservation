from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, request
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app.middleware.auth import apply_rate_limit, csrf_protect, require_admin
from app.repositories.common import get_collection, map_pymongo_error
from app.repositories import availability as availability_repo
from app.utils.time import isoformat_utc, now_utc

bp = Blueprint("admin_availability", __name__)

_ALLOWED_OPS = {"set_rules", "set_exceptions", "set_base_days"}


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


def _availability():
    return get_collection("availability")


def _is_hhmm(v: Any) -> bool:
    if not isinstance(v, str) or len(v) != 5 or v[2] != ":":
        return False
    try:
        h = int(v[:2])
        m = int(v[3:])
        return 0 <= h <= 23 and 0 <= m <= 59
    except Exception:
        return False


def _validate_rule(rule: Dict[str, Any]) -> Optional[str]:
    dows = rule.get("dow")
    if not isinstance(dows, list) or not all(isinstance(x, int) and 0 <= x <= 6 for x in dows):
        return "rule.dow must be int[0..6]"
    if not _is_hhmm(rule.get("start")) or not _is_hhmm(rule.get("end")):
        return "rule.start/end must be 'HH:MM'"
    try:
        slot_min = int(rule.get("slot_min") or 60)
        if slot_min <= 0:
            return "rule.slot_min must be > 0"
    except Exception:
        return "rule.slot_min must be integer"
    brks = rule.get("break", [])
    if brks is not None:
        if not isinstance(brks, list):
            return "rule.break must be list"
        for b in brks:
            if not isinstance(b, dict) or not _is_hhmm(b.get("start")) or not _is_hhmm(b.get("end")):
                return "rule.break[].start/end must be 'HH:MM'"
    svcs = rule.get("services")
    if svcs is not None and (not isinstance(svcs, list) or not all(isinstance(s, str) and s for s in svcs)):
        return "rule.services must be string[]"
    return None


def _validate_exception(ex: Dict[str, Any]) -> Optional[str]:
    date = ex.get("date")
    if not isinstance(date, str) or len(date) != 10:
        return "exception.date must be 'YYYY-MM-DD'"
    if "is_closed" not in ex:
        return "exception.is_closed required"
    if not isinstance(ex.get("is_closed"), bool):
        return "exception.is_closed must be boolean"
    blocks = ex.get("blocks", [])
    if blocks is not None:
        if not isinstance(blocks, list):
            return "exception.blocks must be list"
        for b in blocks:
            if not isinstance(b, dict) or not _is_hhmm(b.get("start")) or not _is_hhmm(b.get("end")):
                return "exception.blocks[].start/end must be 'HH:MM'"
    return None


def _normalize_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rules:
        rc = {
            "dow": list(sorted(set(int(x) for x in r["dow"]))),
            "start": r["start"],
            "end": r["end"],
            "slot_min": int(r.get("slot_min") or 60)
        }
        if r.get("break"):
            rc["break"] = [{"start": b["start"], "end": b["end"]} for b in r["break"]]
        if r.get("services") is not None:
            rc["services"] = [s for s in r.get("services") or [] if isinstance(s, str) and s]
        out.append(rc)
    return out


def _noramalize_exceptions(exceptions: List[Dict[str, Any]]) -> Dict[str, Any]:
    out = []
    for e in exceptions:
        ec = {"date": e["date"], "is_closed": bool(e.get("is_closed"))}
        if e.get("blocks"):
            ec["blocks"] = [{"start": b["start"], "end": b["end"]} for b in e["blocks"]]
        out.append(ec)
    return out


def _serialize_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rules": cfg.get("rules") or [],
        "exceptions": cfg.get("exceptions") or [],
        "base_days": cfg.get("base_days") or [],
        "updated_at": cfg.get("updated_at")
    }


@bp.get("/")
@apply_rate_limit
@require_admin
def get_availabilty_admin():
    try:
        cfg = availability_repo.get_config() or {}
        return _ok(_serialize_config(cfg))
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.patch("/")
@apply_rate_limit
@require_admin
@csrf_protect
def patch_avaliability_admin():
    body = request.get_json(silent=True) or {}
    op = (body.get("op") or "").strip()
    if op not in _ALLOWED_OPS:
        return _err("ERR_INVALID_PAYLOAD", "invalid op")
    value = body.get("value")

    update: Dict[str, Any] = {}
    # Validate & normalize
    if op == "set_rules":
        if not isinstance(value, list):
            return _err("ERR_INVALID_PAYLOAD", "rules must be list")
        for r in value:
            if not isinstance(r, dict):
                return _err("ERR_INVALID_PAYLOAD", "rule must be object")
            msg = _validate_rule(r)
            if msg:
                return _err("ERR_INVALID_PAYLOAD", msg)
        update["rules"] = _normalize_rules(value)
        # updating rules does not change base_days application boundary
        update["updated_at"] = isoformat_utc(now_utc())
    elif op == "set_exceptions":
        if not isinstance(value, list):
            return _err("ERR_INVALID_PAYLOAD", "exception must be list")
        for e in value:
            if not isinstance(e, list):
                return _err("ERR_INVALID_PAYLOAD", "exception must be object")
            msg = _validate_exception(e)
            if msg:
                return _err("ERR_INVALID_PAYLOAD", msg)
        update["exceptions"] = _noramalize_exceptions(value)
        update["updated_at"] = isoformat_utc(now_utc())
    else:   # set_base_days
        if not isinstance(value, list) or not all(isinstance(x, int) and 0 <= x <= 6 for x in value):
            return _err("ERR_INVALID_PAYLOAD", "base_days must be int[0..6]")
        base_days = sorted(set(int(x) for x in value))
        update["base_days"] = base_days
        # Important: updated_at drives "next Monday 00:00 KST" application window
        update["updated_at"] = isoformat_utc(now_utc())

    try:
        doc = _availability().find_one_and_update(
            {"_id": "config"},
            {"$set": update, "$setOnInsert": {"_id": "config", "rules": [], "exceptions": [], "base_days": []}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        # prefer repository read to keep single source of truth (e.g., computed fields)
        cfg = availability_repo.get_config() or (doc or {})
        return _ok(_serialize_config(cfg))
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])