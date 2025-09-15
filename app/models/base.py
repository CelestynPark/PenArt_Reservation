from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from bson import ObjectId

from app.utils.time import iso

__all__ = ["BaseModel"]


UTC = timezone.utc


def _now() -> datetime:
    return datetime.now(UTC)


def _ensure_dt_utc(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)
    if isinstance(v, str):
        s = v.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    raise ValueError("invalid datetime")


def _serialize(val: Any) -> Any:
    if isinstance(val, datetime):
        return iso(val)
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, dict):
        return {k: _serialize(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [_serialize(v) for v in val]
    return val


class BaseModel:
    """
    Mixin-style helper for timestamping and serialization.
    """

    def __init__(self, doc: Optional[dict[str, Any]] = None):
        self._doc: dict[str, Any] = dict(doc or {})
        if "created_at" not in self._doc:
            self._doc["created_at"] = _now()
        else:
            self._doc["created_at"] = _ensure_dt_utc(self._doc["created_at"])
        if "updated_at" not in self._doc:
            self._doc["updated_at"] = self._doc["created_at"]
        else:
            self._doc["updated_at"] = _ensure_dt_utc(self._doc["updated_at"])

    @property
    def created_at(self) -> datetime:
        return _ensure_dt_utc(self._doc.get("created_at"))

    @property
    def updated_at(self) -> datetime:
        return _ensure_dt_utc(self._doc.get("updated_at"))

    def touch(self) -> None:
        """Update only updated_at (idempotent when called on changes)."""
        self._doc["updated_at"] = _now()

    def to_dict(self, fields: Optional[Iterable[str]] = None) -> dict[str, Any]:
        src = self._doc
        out: dict[str, Any] = {}

        # Field selection
        if fields is None:
            keys = list(src.keys())
        else:
            keys = []
            for f in fields:
                if f in src:
                    keys.append(f)
                elif f == "id" and "_id" in src:
                    keys.append("_id")

        for k in keys:
            if k == "_id":
                if "_id" in src:
                    out["id"] = str(src["_id"])
                continue
            v = src.get(k)
            out[k] = _serialize(v)

        # Always serialize timestamps when present
        if "created_at" in src and ("created_at" in out or fields is None):
            out["created_at"] = iso(self.created_at)
        if "updated_at" in src and ("updated_at" in out or fields is None):
            out["updated_at"] = iso(self.updated_at)

        # Include id when no explicit field filter provided
        if fields is None and "_id" in src and "id" not in out:
            out["id"] = str(src["_id"])

        return out

    def to_mongo(self) -> dict[str, Any]:
        """Raw document for MongoDB writes (timestamps ensured, UTC-aware)."""
        d = dict(self._doc)
        d["created_at"] = self.created_at
        d["updated_at"] = self.updated_at
        return d

    @classmethod
    def stamp_new(cls, doc: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        d = dict(doc or {})
        now = _now()
        d.setdefault("created_at", now)
        d.setdefault("updated_at", d["created_at"])
        return d

    @classmethod
    def stamp_update(cls, doc: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        d = dict(doc or {})
        d["updated_at"] = _now()
        return d
