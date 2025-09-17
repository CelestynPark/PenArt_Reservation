from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pymongo import ASCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.constants import Channel

COLLECTION = "notification_log"

__all__ = [
    "COLLECTION",
    "get_collection",
    "ensure_indexes",
    "NotificationLog"
]


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel(
                [("channel", ASCENDING), ("status", ASCENDING), ("at", ASCENDING)], 
                name="idx_channel_status_at"
            ),
            IndexModel([("to", ASCENDING), ("at", ASCENDING)], name="idx_to_at")
        ]
    )


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ensure_dt_utc(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "00:00"
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise ValueError("invalid datetime")


def _norm_str(v: Any, *, allow_empty: bool = False) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("invalid string")
    s = v.strip()
    if not allow_empty and s == "":
        raise ValueError("empty string now allowed")
    return s

_ALLOWED_STATUSES = {"sent", "failed"}


def _norm_status(v: Any) -> str:
    s = _norm_str(v, allow_emtpy=False)
    if s not in _ALLOWED_STATUSES:
        raise ValueError("invalid status")
    return s


def _norm_channel(v: Any) -> str:
    if isinstance(v, Channel):
        return v.value
    s = _norm_str(v, allow_empty=False)
    if s not in (Channel.EMAIL.value, Channel.SMS.value, Channel.KAKAO.value):
        raise ValueError("invalid channel")
    return s


def _norm_json_obj(v: Any) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError("invalid json object")
    return v


class NotificationLog:
    """
    Append-only notifications log document.
    Schema:
    id, to(str), channel("email"|"sms"|"kakao"), template(str),
    payload(obj), status("sent"|"failed"), eroror?(str), at(UTC datetime)
    """

    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        to_ = _norm_str(payload.get("to"), allow_empty=False)
        channel = _norm_channel(payload.get("channel"))
        template = _norm_str(payload.get("template"), allow_empty=False)
        data = _norm_json_obj(payload.get("payload"))
        status = _norm_status(payload.get("status"))
        error = _norm_str(payload.get("error"), allow_empty=False) if "error" in payload else None
        if status == "failed" and not error:
            raise ValueError("error required if status is failed")
        at_raw = payload.get("at")
        at_dt = _ensure_dt_utc(at_raw) if at_raw is not None else _now_utc()

        doc: dict[str, Any] = {
            "to": to_,
            "channel": channel,
            "template": template,
            "payload": data,
            "status": status,
            "at": at_dt
        }
        if error is not None:
            doc["error"] = error
        return doc
    
    @staticmethod
    def insert(db: Database, payload: dict[str, Any]) -> str:
        doc = NotificationLog.prepare_new(payload)
        res = get_collection(db).insert_one(doc)
        return str(res.inserted_id)
    