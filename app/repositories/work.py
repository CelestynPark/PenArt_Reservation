from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.repositories.common import (
    get_collection,
    in_txn,
    map_pymongo_error
)
from app.utils.time import now_utc, isoformat_utc
from app.utils.validation import validate_pagination, ValidationError

_ALLOWED_SORT_FIELDS: Tuple[str, ...] = ("created_at", "order", "_id")


class RepoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _col() -> Collection:
    return get_collection("works")


def _to_obj_id(s: str) -> ObjectId:
    try:
        return ObjectId(str(s))
    except Exception:
        raise RepoError("ERR_INVALID_PAYLOAD", "invalid id")
    

def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _stringify_id(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if doc is None:
        return None
    doc["id"] = str(doc.get("_id"))
    return doc


def _apply_visibility_filter(q: Dict[str, Any], is_visible: Optional[bool]) -> None:
    if is_visible is not None:
        q["is_visible"] = bool(is_visible)


def _apply_author_filter(q: Dict[str, Any], author: Optional[str]) -> None:
    if author:
        a = author.strip().lower()
        if a not in {"artist", "student"}:
            raise RepoError("ERR_INVALID_PAYLOAD", "author must be 'artist' or 'student'")
        q["author_type"] = a
    

def _apply_tags_filter(q: Dict[str, Any], tags: Optional[Iterable[str]]) -> None:
    if not tags:
        return
    ts = [t for t in (s.strip() for s in tags) if t]
    if ts:
        q["tags"] = {"$in": ts}


def _apply_query_filter(q: Dict[str, Any], text: Optional[str]) -> None:
    if not text:
        return
    s = text.strip()
    if not s:
        return
    # 간단 부분 일치(ko/en 제목/설명)
    regex = {"$regex": s, "$options": "i"}
    q["$or"] = [
        {"title_i18n.ko": regex},
        {"title_i18n.en": regex},
        {"description_i18n.ko": regex},
        {"description_i18n.en": regex},
        {"tags": {"$in": [s]}}
    ]


def _pymongo_sort(sort_pairs: List[Tuple[str, str]]) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    for f, d in sort_pairs:
        out.append((f, ASCENDING if d == "asc" else DESCENDING))
    return out


def find_by_id(work_id: str) -> Optional[Dict[str, Any]]:
    oid = _to_obj_id(work_id)
    try:
        doc = _col().find_one({"_id": oid})
        return _stringify_id(doc)
    except PyMongoError as e:
        m = map_pymongo_error(e)
        raise RepoError(m["code"], m["message"])
    

def list_works(
    author: Optional[str] = None,
    tags: Optional[List[str]] = None,
    is_visible: Optional[bool] = None,
    q: Optional[str] = None,
    page: int = 1,
    size: int = 20,
    sort: str = "order:asc, created_at:desc"
) -> Dict[str, Any]:
    try:
        _, _, sort_pairs = validate_pagination(
            {"page": page, "size": size, "sort": sort},
            default_size=size,
            max_size=100,
            allowed_sort_fields=_ALLOWED_SORT_FIELDS
        )
    except ValidationError as e:
        raise RepoError(e.code, str(e))
    
    query: Dict[str, Any] = {}
    _apply_visibility_filter(query, is_visible)
    _apply_author_filter(query, author)
    _apply_tags_filter(query, tags)
    _apply_query_filter(query, q)

    try:
        total = _col().count_documents(query)
        cursor = (
            _col()
            .find(query)
            .sort(_pymongo_sort(sort_pairs) if sort_pairs else [("order", ASCENDING), ("created_at", DESCENDING)])
            .skip((max(page, 1) -1) * max(size, 1))
            .limit(max(size, 1))
        )

        items: List[Dict[str, Any]] = []
        for doc in cursor:
            items.append(_stringify_id(doc) or {})

        return {"items": items, "total": int(total), "page": int(max(page, 1)), "size": int(max(size, 1))}
    except PyMongoError as e:
        m = map_pymongo_error(e)
        raise RepoError(m["code"], m["message"])
    

def create_work(doc: Dict[str, Any], *, by: Dict[str, Any]) -> str:
    if not isinstance(doc, dict):
        raise RepoError("ERR_INVALID_PAYLOAD", "payload must be object")
    now_iso = _now_iso()
    doc = {**doc, "created_at": now_iso, "updated_at": now_iso}
    try:
        with in_txn() as s:
            res = _col().insert_one(doc, session=s)
            return str(res.inserted_id)
    except PyMongoError as e:
        m = map_pymongo_error(e)
        raise RepoError(m["code"], m["message"])
    

def update_work(work_id: str, patch: Dict[str, Any], *, by: Dict[str, Any]) -> bool:
    if not isinstance(patch, dict):
        raise RepoError("ERR_INVALID_PAYLOAD", "patch must be object")
    oid = _to_obj_id(work_id)
    update = {"$set": {**patch, "updated_at": _now_iso()}}
    try:
        with in_txn() as s:
            res = _col().update_one({"_id": oid}, update, session=s)
            if res.matched_count == 0:
                return False
            return True    # 멱등: 내용 동일해도 True
    except PyMongoError as e:
        m = map_pymongo_error(e)
        raise RepoError(m["code"], m["message"])
        

def delete_work(work_id: str, *, by: Dict[str, Any]) -> bool:
    oid = _to_obj_id(work_id)
    try:
        with in_txn() as s:
            res = _col().delete_one({"_id": oid}, session=s)
            return res.deleted_count > 0
    except PyMongoError as e:
        m = map_pymongo_error(e)
        raise RepoError(m["code"], m["message"])
    