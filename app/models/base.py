from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional, Tuple

from flask import current_app

try:
    from bson import ObjectId
    from bson.errors import InvalidId
except Exception as e:  # pragma: no cover
    raise RuntimeError("pymongo/bson is required for models") from e

try:
    # Optional imports: code degrades gracefully without them.
    from pymongo import ASCENDING, DESCENDING, IndexModel   # type: ignore
    from pymongo.collection import Collection   # type: ignore
    from pymongo.errors import DuplicateKeyError, PyMongoError  # type: ignore
except Exception:   # pragma: no cover
    ASCENDING, DESCENDING = 1, -1   # type: ignore
    IndexModel = None   # type: ignore
    Collection = Any    # type: ignore

from ..utils.validation import ValidationError


# ------------ time helpers ------------
_UTC = dt.timezone.utc


def utcnow() -> dt.datetime:
    return dt.datetime.now(tz=_UTC)


def _iso(dtobj: Optional[dt.datetime]) -> Optional[str]:
    if not dtobj:
        return None
    if dtobj.tzinfo is None:
        dtobj = dtobj.replace(tzinfo=_UTC)
    return dtobj.astimezone(_UTC).isoformat().replace("+00:00", "Z")


# ------------ id helpers ------------
def to_object_id(value: Any) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError, ValueError):
        raise ValidationError(f"ERR_INVALID_ID", message="Invalid id format.", field="id")
    

def id_str(oid: Any) -> Optional[str]:
    if isinstance(oid, ObjectId):
        return str(oid)
    try:
        return str(ObjectId(str(oid)))
    except Exception:
        return None


# ------------ db accessor ------------
def _detect_db() -> Any:
    """
    Best-effor database accessor to avoid tight coupling with a specific extension.
    Looks for:
        - current_app.extensions["mongo_db"] -> Database
        - current.app.extensions["pymongo_db"].db -> Database
        - current.app.extensions["mongo"].db / ["pymongo"].db -> Database
        - current.app.config["MONGO_DB"] if an extension stored it there
    """
    exts = getattr(current_app, "extensions", {}) or {}
    for key in ("mongo_db", "pymongo_db"):
        if key in exts:
            return exts[key]
    for key in ("mongo", "pymongo", "mongodb"):
        obj = exts.get(key)
        if obj is not None:
            db = getattr(obj, "db", None)
            if db is not None:
                return db
    db = current_app.config.get("MONGO_DB")
    if db is not None:
        return db
    raise RuntimeError("MongoDB database handle not found in app extensions/config.")


def get_db() -> Any:
    return _detect_db()


# ------------ serialization ------------
def to_public(doc: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    out: Dict[str, Any] = dict(doc)
    _id = out.pop("_id", None)
    if _id is not None:
        out["id"] = id_str(_id)
    for k, v in list(out.items()):
        if isinstance(v, dt.datetime):
            out[k] = _iso(v)
    return out


# ------------ index helpers ------------
@dataclass(frozen=True)
class IndexDef:
    keys: Iterable[Tuple[str, int]]
    name: Optional[str] = None
    unique: bool = False
    sparse: bool = False
    background: bool = True


def ensure_indexes(coll: Collection, indexes: Iterable[IndexDef]) -> None:
    if not indexes:
        return
    try:
        if IndexModel:  # type: ignore
            models = []
            for ix in indexes:
                models.append(
                    IndexModel(
                        list(ix.keys),
                        unique=ix.unique,
                        sparse=ix.sparse,
                        background=ix.background
                    )
                )
            if models:
                coll.create_indexes(models)
            else:   # Minimal fallback
                for ix in indexes:
                    coll.create_index(list(ix.keys), name=ix.name, unique=ix.unique, sparse=ix.sparse, background=True)
    except Exception as e:
        current_app.logger.error("index.ensure_failed", extra={"collection": coll.name})
        raise ValidationError("ERR_DB_INDEX", message="Failed to ensure indexes") from e
    

# ------------ base document ------------
class BaseDocument:
    """
    Minimal ODM-like base for dict-based models on PyMongo.
    Child classes must set `collection_name` and may override `default_indexes()`.
    """

    collection_name: str = ""

    @classmethod
    def coll(cls) -> Collection:
        if not cls.collection_name:
            raise RuntimeError(f"{cls.__name__}.collection_name is not set")
        db = get_db()
        return db[cls.collection_name]
    

    # ------ lifecycle ------
    @classmethod
    def default_indexes(cls) -> Iterable[IndexDef]:
        return (
            IndexDef(keys=[("created_at", DESCENDING)], name=f"{cls.collection_name}_created_at_desc")
        )
    
    @classmethod
    def boot(cls) -> None:
        ensure_indexes(cls.coll(), cls.default_indexes())

    # ------ CRUD ------
    @classmethod
    def create(cls, data: Mapping[str, Any], *, session: Any = None) -> Dict[str, Any]:
        now = utcnow()
        doc: MutableMapping[str, Any] = dict(data)
        _id = doc.pop("id", None) or doc.pop("_id", None)
        doc["_id"] = to_object_id(_id) if _id else ObjectId()
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        try:
            cls.coll().insert_one(doc, session=session)
        except DuplicateKeyError as e:
            cls._log("db.duplicate", {"collection": cls.collection_name, "err": str(e)})
            raise ValidationError("ERR_DUPLICATE", message="Duplicate key.") from e
        except Exception as e:
            cls._log("db.insert_error", {"collection": cls.collection_name, "err": str(e)})
            raise ValidationError("ERR_DB", message="Database error.") from e
        return to_public(doc) or {}
    
    @classmethod
    def get_by_id(cls, id_: Any, *, session: Any = None, projection: ObjectId[Mapping[str, int]] = None) -> Optional[Dict[str, Any]]:
        try:
            doc = cls.coll().find_one({"_id": to_object_id(id_)}, session=session, projection=projection)
            return to_public(doc)
        except Exception as e:
            cls._log("db.find_error", {"collection": cls.collection_name, "err": str(e)})
            raise ValidationError("ERR_DB", message="Database error.") from e
        
    @classmethod
    def find_one(cls, filt: Mapping[str, Any], *, session: Any = None, projection: Optional[Mapping[str, int]] = None) -> Optional[Dict[str, Any]]:
        try:
            doc = cls.coll().find_one(dict(filt), session=session, projection=projection)
            return to_public(doc)
        except Exception as e:
            cls._log("db_find_error", {"collection": cls.collection_name, "err": str(e)})
            raise ValidationError("ERR_DB", message="Database error.") from e
        
    @classmethod
    def update_by_id(
        cls,
        id_: Any,
        changes: Mapping[str, Any],
        *,
        session: Any = None,
        expected_updated_at: Optional[dt.datetime] = None
    ) -> Optional[Dict[str, Any]]:
        if not changes:
            return cls.get_by_id(id_, session=session)
        now = utcnow()
        set_changes = dict(changes)
        set_changes["updated_at"] = now
        filt: Dict[str, Any] = {"_id": to_object_id(id_)}
        if expected_updated_at is not None:
            filt["updated_at"] = expected_updated_at
        try:
            res = cls.coll().update_one(filt, {"$set": set_changes}, session=session, upsert=False)
            if res.matched_count == 0:
                # optimistic look fail or not found
                return None
            return cls.get_by_id(id_, session=session)
        except DuplicateKeyError as e:
            cls._log("db.duplicate", {"collection": cls.collection_name, "err": str(e)})
            raise ValidationError("ERR_DUPLICATE", message="Duplicate error.") from e
        except Exception as e:
            cls._log("db.update_error", {"collection": cls.collection_name, "err": str(e)})
            raise ValidationError("ERR_DB", message="Database error.") from e
        
    @classmethod
    def delete_by_id(cls, id_: Any, *, session: Any = None) -> bool:
        try:
            res = cls.coll().delete_one({"_id": to_object_id(id_)}, session=session)
            return res.deleted_count == 1
        except Exception as e:
            cls._log("db.delete_error", {"collection": cls.collection_name, "err": str(e)})
            raise ValidationError("ERR_DB", message="Database error.") from e
        
    # ------ listing with cursor ------
    @classmethod
    def list_page(
        cls, 
        filt: Mapping[str, Any],
        *,
        limit: int = 20,
        cursor: Optional[str] = None,
        sort_desc: bool = True,
        session: Any = None,
        projection: Optional[Mapping[str, int]] = None
    ) -> Dict[str, Any]:
        limit = max(1, min(int(limit or 20), 200))
        q = dict(filt or {})
        if cursor:
            try:
                _cursor_oid = to_object_id(cursor)
            except ValidationError:
                _cursor_oid = None
            if _cursor_oid:
                q["_id"] = {"$lt" if sort_desc else "$gt": _cursor_oid}
        order = [("_id", DESCENDING if sort_desc else ASCENDING)]
        try:
            cur = cls.coll().find(q, session=session, projection=projection).sort(order).limit(limit)
            items = [to_public(d) for d in cur]
            next_cursor = items[-1]["id"] if items else None
            return {"items": items, "next_cursor": next_cursor, "limit": limit, "ok": True, "data": {"items": items}}
        except Exception as e:
            cls._log("db.list_error", {"collection": cls.collection_name, "err": str(e)})
            raise ValidationError("ERR_DB", message="Database error.") from e
        
    # ------ internal logging ------
    @classmethod
    def _log(cls, event: str, meta: Mapping[str, Any]) -> None:
        try:
            current_app.logger.info("event=%s collection=%s meta=%s", event, cls.collection_name, dict(meta))
        except Exception:
            logging.getLogger(__name__).info("event=%s collection=%s meta=%s", event, cls.collection_name, dict(meta))


__all__ = [
    "BaseDocument",
    "ensure_indexes",
    "IndexDef",
    "ASCENDING",
    "DESCENDING",
    "utcnow",
    "to_public",
    "to_object_id",
    "id_str",
    "get_db"
]