from __future__ import annotations

from typing import Any, Iterable, Optional, Tuple, Union

from pymongo import ReturnDocument, errors as pymongo_errors
from pymongo.client_session import ClientSession
from pymongo.collection import Collection
from pymongo.database import Database

from app.repositories.common import (
    with_session,
    with_tx,
    InternalError,
    RepoError
)
from app.models import availability as av


__all__ = [
    "get_rules",
    "update_rules",
    "get_exceptions",
    "set_exception",
    "get_base_days",
    "set_base_days",
    "find_applicable_rules"
]


class InvalidPayloadError(RepoError):
    code = "ERR_INVALID_PAYLOAD"


def _col(db: Database) -> Collection:
    return av.get_collection(db)


def _ensure_indexes(db: Database) -> None:
    av.ensure_indexes(db)


def _load_or_init(db: Database, session: Optional[ClientSession] = None) -> dict:
    _ensure_indexes(db)
    doc = _col(db).find_one({}, session=session)
    if doc:
        return doc
    base = av.Availability.prepare_new({"rules": [], "exceptions": [], "base_days": []})
    _col(db).insert_one(base, session=session)
    return _col(db).find_one({}, session=session) or base


def _normalize_update(partial: dict[str, Any]) -> dict[str, Any]:
    try:
        return av.Availability.prepare_update(partial)
    except Exception as e:
        raise InvalidPayloadError(str(e)) from e
    

def get_rules() -> list[dict]:
    def _fn(db: Database, session: ClientSession):
        doc = _load_or_init(db, session)
        return list(doc.get("rules", []))
    
    try:
        return with_session(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def update_rules(rules: Iterable[dict[str, Any]]) -> list[dict]:
    upd = _normalize_update({"rules": list(rules)})

    def _fn(db: Database, session: ClientSession):
        _load_or_init(db, session)
        res = _col(db).find_one_and_update(
            {},
            {"$set": upd},
            session=session,
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        return list(res.get("rules", [])) if res else []
    
    try:
        return with_tx(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def _parse_range_arg(
        date_range: Union[Tuple[str, str], list[str], dict[str, str], None]
) -> Optional[Tuple[str, str]]:
    if date_range is None:
        return None
    if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
        a, b = str(date_range[0]), str(date_range[1])
        return (a, b) if a <= b else (b, a)
    if isinstance(date_range, dict):
        a = date_range.get("start") or date_range.get("from")
        b = date_range.get("end") or date_range.get("to")
        if isinstance(a, str) and isinstance(b, str):
            return (a, b) if a <= b else (b, a)
    raise InvalidPayloadError("invalid range")


def get_exceptions(
        date_range: Union[Tuple[str, str], list[str], dict[str, str], None]
) -> list[dict]:
    rng = _parse_range_arg(date_range)

    def _fn(db: Database, session: ClientSession):
        doc = _load_or_init(db, session)
        items: list[dict] = list(doc.get("exceptions", []))
        if not rng:
            return items 
        s, e = rng
        return [x for x in items if isinstance(x.get("date"), str) and s <= x["date"] <= e]

    try:
        return with_session(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def set_exception(date_str: str, patch: dict[str, Any]) -> dict:
    if not isinstance(date_str, str) or not isinstance(patch, dict):
        raise InvalidPayloadError("invalid payload")
    norm = _normalize_update({"exceptions": [{"date": date_str, **patch}]})
    new_ex = norm["exception"][0]

    def _fn(db: Database, session: ClientSession):
        doc = _load_or_init(db, session)
        arr: list[dict] = list(doc.get("exceptions", []))
        idx = next((i for i, x in enumerate(arr) if x.get("date") == new_ex["date"]), -1)
        if idx >= 0:
            arr[idx] = new_ex
        else:
            arr.append(new_ex)
        upd = av.Availability.prepare_update({"exceptions": arr})
        res = _col(db).find_one_and_update(
            {},
            {"$set": upd},
            session=session,
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        # return the normalized single exception as source of truth
        return new_ex
    
    try:
        return with_tx(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def get_base_days() -> list[int]:
    def _fn(db: Database, session: ClientSession):
        doc = _load_or_init(db, session)
        return list(doc.get("base_days", []))
    
    try:
        return with_session(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
    

def set_base_days(days: Iterable[int]) -> list[int]:
    upd = _normalize_update({"base_days": list(days)})

    def _fn(db: Database, session: ClientSession):
        _load_or_init(db, session)
        res = _col(db).find_one_and_update(
            {},
            {"$set": upd},
            session=session,
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        return list(res.get("base_days", [])) if res else []
    
    try:
        return with_tx(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InvalidPayloadError("dow must be 0..6")
    

def find_applicable_rules(dow: int, service_id: Optional[str] = None) -> list[dict]:
    try:
        d = int(dow)
        if d < 0 or d > 6:
            raise ValueError
    except Exception:
        raise InvalidPayloadError("dow must be 0..6") 
    
    def _fn(db: Database, session: ClientSession):
        doc = _load_or_init(db, session)
        rules: list[dict] = list(doc.get("rules", []))
        out: list[dict] = []
        for r in rules:
            r_dows = r.get("dow") or []
            if d not in r_dows:
                continue
            svc = r.get("services")
            if service_id and isinstance(svc, list) and svc:
                if service_id not in svc:
                    continue
            out.append(r)
        out.sort(key=lambda x: (str(x.get("start", "00:00")), str(x.get("end", "00:00"))))
        return out
    
    try:
        return with_session(_fn)
    except RepoError:
        raise
    except pymongo_errors.PyMongoError as e:
        raise InternalError(str(e)) from e
