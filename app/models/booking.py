from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

from app.models.base import TIMESTAMP_FIELDS
from app.utils.time import isoformat_utc, now_utc

__all__ = [
    "collection_name",
    "schema_fields",
    "indexes",
    "compute_end_at",
    "normalize_booking",
]


collection_name = "bookings"

schema_fields: Dict[str, Any] = {
    "id": {"type": "objectid?", "readonly": True},
    "code": {"type": "string?", "index": True},
    "customer_id": {"type": "string", "required": True},
    "service_id": {"type": "string", "required": True},
    "start_at": {"type": "string", "format": "iso8601", "required": True},  # UTC
    "end_at": {"type": "string", "format": "iso8601"},  # UTC
    "status": {
        "type": "string",
        "enum": ["requested", "confirmed", "completed", "canceled", "no_show"],
        "default": "requested",
    },
    "note_customer": {"type": "string?"},
    "note_internal": {"type": "string?"},
    "uploads": {"type": "array", "items": {"type": "string"}, "default": []},
    "policy_agreed_at": {"type": "string?", "format": "iso8601"},
    "source": {"type": "string", "enum": ["web", "admin", "kakao"], "default": "web"},
    "history": {
        "type": "array",
        "items": {
            "type": "object",
            "schema": {
                "at": {"type": "string", "format": "iso8601"},
                "by": {"type": "string?"},
                "from": {
                    "type": "string?",
                    "enum": ["requested", "confirmed", "completed", "canceled", "no_show"],
                },
                "to": {
                    "type": "string",
                    "enum": ["requested", "confirmed", "completed", "canceled", "no_show"],
                },
                "reason": {"type": "string?"},
            },
        },
        "default": [],
    },
    "reschedule_of": {"type": "string?"},
    "canceled_reason": {"type": "string?"},
    TIMESTAMP_FIELDS[0]: {"type": "string?", "format": "iso8601"},
    TIMESTAMP_FIELDS[1]: {"type": "string?", "format": "iso8601"},
}

indexes = [
    (
        {"keys": [("service_id", 1), ("start_at", 1)], "options": {"name": "service_id_1_start_at_1", "unique": True, "background": True}}
    ),
    ({"keys": [("code", 1)], "options": {"name": "code_1", "background": True}}),
    (
        {
            "keys": [("customer_id", 1), ("start_at", -1)],
            "options": {"name": "customer_id_1_start_at_-1", "background": True},
        }
    ),
    ({"keys": [("status", 1)], "options": {"name": "status_1", "background": True}}),
    ({"keys": [("created_at", -1)], "options": {"name": "created_at_-1", "background": True}}),
]


class BookingPayloadError(ValueError):
    code = "ERR_INVALID_PAYLOAD"


ALLOWED_STATUS = {"requested", "confirmed", "completed", "canceled", "no_show"}
ALLOWED_SOURCE = {"web", "admin", "kakao"}


def _ensure_mapping(doc: Mapping) -> None:
    if not isinstance(doc, Mapping):
        raise BookingPayloadError("document must be a mapping/dict")


def _clean_str(v: Any) -> Optional[str]:
    return v.strip() if isinstance(v, str) else None


def _now_iso() -> str:
    return isoformat_utc(now_utc())


@dataclass(frozen=True)
class _IsoDT:
    raw: str

    @staticmethod
    def parse(s: Any, field: str) -> _IsoDT:
        if not isinstance(s, str) or not s:
            raise BookingPayloadError(f"{field} must be ISO8601 string (UTC)")
        # Do not fully parse with timezone libs here; keep lightweight schema-level guard.
        # Accept the string and rely on upstream parser/validators where needed.
        return _IsoDT(raw=s)


def _norm_status(v: Any) -> str:
    if not isinstance(v, str) or v.strip() == "":
        return "requested"
    s = v.strip()
    if s not in ALLOWED_STATUS:
        raise BookingPayloadError("status is invalid")
    return s


def _norm_source(v: Any) -> str:
    if not isinstance(v, str) or v.strip() == "":
        return "web"
    s = v.strip()
    if s not in ALLOWED_SOURCE:
        raise BookingPayloadError("source is invalid")
    return s


def _norm_history(items: Iterable[Mapping[str, Any]] | None) -> list[Dict[str, Any]]:
    out: list[Dict[str, Any]] = []
    for i, h in enumerate(items or []):
        if not isinstance(h, Mapping):
            raise BookingPayloadError(f"history[{i}] must be an object")
        at = _IsoDT.parse(h.get("at"), f"history[{i}].at").raw
        to = _clean_str(h.get("to")) or ""
        if to not in ALLOWED_STATUS:
            raise BookingPayloadError(f"history[{i}].to is invalid")
        fr = _clean_str(h.get("from"))
        if fr is not None and fr not in ALLOWED_STATUS:
            raise BookingPayloadError(f"history[{i}].from is invalid")
        by = _clean_str(h.get("by"))
        reason = _clean_str(h.get("reason"))
        rec = {"at": at, "to": to}
        if fr:
            rec["from"] = fr
        if by:
            rec["by"] = by
        if reason:
            rec["reason"] = reason
        out.append(rec)
    return out


def compute_end_at(start_at_utc: datetime, duration_min: int) -> datetime:
    if not isinstance(start_at_utc, datetime):
        raise BookingPayloadError("start_at_utc must be a datetime")
    try:
        dur = int(duration_min)
    except Exception as e:
        raise BookingPayloadError("duration_min must be integer") from e
    if dur <= 0:
        raise BookingPayloadError("duration_min must be > 0")
    return start_at_utc + timedelta(minutes=dur)


def normalize_booking(doc: Mapping[str, Any]) -> Dict[str, Any]:
    _ensure_mapping(doc)
    src = deepcopy(dict(doc))
    out: MutableMapping[str, Any] = {}

    # required ids
    svc_id = _clean_str(src.get("service_id"))
    if not svc_id:
        raise BookingPayloadError("service_id is required")
    out["service_id"] = svc_id

    cust_id = _clean_str(src.get("customer_id"))
    if not cust_id:
        raise BookingPayloadError("customer_id is required")
    out["customer_id"] = cust_id

    # time fields (UTC strings)
    start_at = _IsoDT.parse(src.get("start_at"), "start_at").raw
    out["start_at"] = start_at

    end_at = src.get("end_at")
    if end_at is not None:
        out["end_at"] = _IsoDT.parse(end_at, "end_at").raw

    # meta
    code = _clean_str(src.get("code"))
    if code:
        out["code"] = code

    out["status"] = _norm_status(src.get("status"))
    out["source"] = _norm_source(src.get("source"))

    note_customer = _clean_str(src.get("note_customer"))
    if note_customer:
        out["note_customer"] = note_customer

    note_internal = _clean_str(src.get("note_internal"))
    if note_internal:
        out["note_internal"] = note_internal

    uploads = []
    for u in src.get("uploads") or []:
        if isinstance(u, str) and u.strip():
            uploads.append(u.strip())
    out["uploads"] = uploads

    pol_agreed = src.get("policy_agreed_at")
    if pol_agreed is not None:
        out["policy_agreed_at"] = _IsoDT.parse(pol_agreed, "policy_agreed_at").raw

    reschedule_of = _clean_str(src.get("reschedule_of"))
    if reschedule_of:
        out["reschedule_of"] = reschedule_of

    canceled_reason = _clean_str(src.get("canceled_reason"))
    if canceled_reason:
        out["canceled_reason"] = canceled_reason

    out["history"] = _norm_history(src.get("history"))

    # timestamps
    now_iso = _now_iso()
    created = _clean_str(src.get(TIMESTAMP_FIELDS[0]))
    updated = _clean_str(src.get(TIMESTAMP_FIELDS[1]))
    out[TIMESTAMP_FIELDS[0]] = created or now_iso
    out[TIMESTAMP_FIELDS[1]] = updated or now_iso

    return dict(out)
