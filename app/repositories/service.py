from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.collection import Collection
from pymongo.client_session import ClientSession
from pymongo.errors import PyMongoError

from app.repositories.common import get_collection, in_txn, map_pymongo_error
from app.utils.time import now_utc, isoformat_utc

__all__ = [
    "RepoError",
    "get_by_id",
    "find_by_slug",
    "list_active",
    "admin_list",
    "update_fields"
]


class RepoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    
def _services() -> Collection:
    return get_collection("services")


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "invalid id") from e
    

def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _page_args(page: int, size: int, max_size: int = 100) -> Tuple[int, int]:
    p = int(page) if isinstance(page, int) else 1
    s = int(size) if isinstance(size, int) else 20
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > max_size:
        s = max_size
    return p, s


def _parse_sort(sort: Optional[str], default: Tuple[str, int] = ("order", 1)) -> List[Tuple[str, int]]:
    allowed = {"order", "created_at", "updated_at", "name_i18n.ko"}
    if not isinstance(sort, str) or ":" not in sort:
        return [default]
    field, direction = sort.split(":", 1)  
    field = field.strip()
    direction = direction.strip().lower()
    if field not in allowed:
        return [default]
    order = -1 if direction == "desc" else 1
    return [(field, order)]


def get_by_idd(service_id: str) -> Dict[str, Any] | None:
    try:
        oid = _oid(service_id)
    except RepoError:
        # tolerate non-ObjectId ids if upstream provided custom ids
        oid = None
    filt: Dict[str, Any] = {"_id": oid} if oid is not None else {"_id": service_id}
    try:
        return _services().find_one(filt)
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def find_by_slug(slug: str) -> Dict[str, Any] | None:
    if not isinstance(slug, str) or not slug.strip():
        raise RepoError("ERR_INVALID_PAYLOAD", "slug required")
    try:
        return _services().find_one({"slug": slug.strip()})
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def list_active(page: int = 1, size: int = 20, sort: str = "order:asc") -> Dict[str, Any]:
    p, s = _page_args(page, size, 100)
    filt = {"is_active": True}
    try:
        total = _services().count_documents(filt)
        cursor = (
            _services()
            .find(filt)
            .sort(_parse_sort(sort, {"order", 1}))
            .skip((p - 1) * s)
            .limit(s)
        )
        items = list(cursor)
        return {"items": items, "total": total, "page": p, "size": s}
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def admin_list(
    page: int = 1,
    size: int = 20,
    sort: str | None = None,
    filters: Dict[str, Any] | None = None
) -> Dict[str, Any]:
    p, s = _page_args(page, size, 100)
    filt: Dict[str, Any] = {}
    f = dict(filters or {})
    if "is_active" in f:
        if isinstance(f["is_active"], bool):
            filt["is_active"] = f["is_active"]
        elif isinstance(f["is_active"], str):
            v = f["is_active"].strip().lower()
            if v in {"true", "1", "yes", "on"}:
                filt["is_active"] = True
            elif v in {"false", "0", "no", "off"}:
                filt["is_active"] = False
    if "level" in f and isinstance(f["level"], str) and f["level"].strip():
        filt["level"] = f["level"].strip()
    if "featured" in f:
        val = f["featured"]
        if isinstance(val, bool):
            filt["featured"] = val
        elif isinstance(val, str):
            v = val.strip().lower()
            if v in {"true", "1", "yes", "on"}:
                filt["featured"] = True
            elif v in {"false", "0", "no", "off"}:
                filt["featured"] = False
    if "q" in f and isinstance(f["q"], str) and f["q"].strip():
        q = f["q"].strip()
        filt["$or"] = [
            {"name_i18n.ko": {"$regex": q, "$options": "i"}},
            {"name_i18n.en": {"$regex": q, "$options": "i"}}
        ]

    try:
        total = _services().count_documents(filt)
        cursor = (
            _services()
            .find(filt)
            .sort(_parse_sort(sort, {"order", 1}))
            .skip((p - 1) * s)
            .limit(s)
        )
        items = list(cursor)
        return {"items": items, "total": total, "page": p, "size": s}
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def update_fields(service_id: str, patch: Dict[str, Any], session: ClientSession | None = None) -> Dict[str, Any]:
    if not isinstance(patch, dict) or not patch:
        raise RepoError("ERR_INVALID_PAYLOAD", "patch must be non-emptry dict")
    try:
        oid = _oid(service_id)
    except RepoError:
        oid = None
    filt: Dict[str, Any] = {"_id": oid} if oid is not None else {"_id": service_id}
    upd = {"$set": dict(patch)}
    upd["$set"]["updated_at"] = _now_iso()

    try:
        with in_txn(session) as s:
            doc = _services().find_one_and_update(
                filt, 
                upd,
                return_document=ReturnDocument.AFTER,
                session=s
            )
            if not doc:
                raise RepoError("ERR_NOT_FOUND", "service not found")
            return doc
    except RepoError:
        raise
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

