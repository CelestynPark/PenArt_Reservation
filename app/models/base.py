from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional, Type, TypeVar

from bson import ObjectId

from app.utils.time import now_utc, parse_iso8601, to_iso8601

T = TypeVar("T", bound="BaseModel")


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("naive datetime is not allowed")
    return dt.astimezone(timezone.utc)


def _coerce_dt(value: Any, default: Optional[datetime] = None) -> datetime:
    if value is None:
        return (default or now_utc()).astimezone(timezone.utc)
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, str):
        return _ensure_utc(parse_iso8601(value))
    raise ValueError("invalid datetime value")


def _coerce_id(value: Any) -> Optional[ObjectId]:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and value:
        return ObjectId(value)
    raise ValueError("invalid id")


class BaseModel:
    __collection__: Optional[str] = None

    id: Optional[ObjectId]
    created_at: datetime
    updated_at: datetime

    def __init__(
        self,
        *,
        id: ObjectId | str | None = None,
        created_at: datetime | str | None = None,
        updated_at: datetime | str | None = None,
    ) -> None:
        self.id = _coerce_id(id)
        now = now_utc()
        self.created_at = _coerce_dt(created_at, default=now)
        self.updated_at = _coerce_dt(updated_at, default=self.created_at)

    def touch(self) -> None:
        self.updated_at = now_utc()

    @classmethod
    def collection_name(cls) -> str:
        if not cls.__collection__:
            raise NotImplementedError("collection name must be defined on subclass via __collection__")
        return cls.__collection__  # type: ignore[return-value]

    def to_dict(self, exclude_none: bool = True) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "id": str(self.id) if self.id is not None else None,
            "created_at": to_iso8601(self.created_at),
            "updated_at": to_iso8601(self.updated_at),
        }
        if exclude_none:
            return {k: v for k, v in out.items() if v is not None}
        return out

    @classmethod
    def from_dict(cls: Type[T], d: Dict[str, Any]) -> T:
        obj: T = cls.__new__(cls)  # bypass __init__ to avoid subclass arg conflicts
        # id field: accept "_id" or "id"
        raw_id = d.get("_id", d.get("id"))
        setattr(obj, "id", _coerce_id(raw_id))
        # timestamps
        created = d.get("created_at")
        updated = d.get("updated_at")
        setattr(obj, "created_at", _coerce_dt(created))
        setattr(obj, "updated_at", _coerce_dt(updated, default=getattr(obj, "created_at")))
        return obj
