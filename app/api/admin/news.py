from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from flask import Blueprint, request
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import PyMongoError

from app.middleware.auth import apply_rate_limit, csrf_protect, require_admin
from app.repositories.common import get_collection, map_pymongo_error
from app.utils.time import isoformat_utc, now_utc

bp = Blueprint("admin_news", __name__)

NEWS_ALLOWED_STATUS = ["draft", "scheduled", "published"]
_ALLOWED_SORT_FIELDS = ("created_at", "updated_at", "published_at", "title_i18n.ko", "_id")


def _http_for(code: str) -> int:
    return {
        "ERR_INTERNAL_PAYLOAD": 400,
        "ERR_UNAUTHORIZED": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_CONFLICT": 409,
        "ERR_POLICY_CUTOFF": 409,
        "ERR_RATE_LIMIT": 429,
        "ERR_INTERNAL": 500
    }.get(code or "", 400)
    

def _ok(data: Any, status: int = 200) -> Tuple[Dict[str, Any], int]:
    return ({"ok": True, "data": data}, status)


def _err(code: str, message: str) -> Tuple[Dict[str, Any], int]:
    return ({"ok": False, "error": {"code": code, "message": message}}, _http_for(code))


def _oid(s: str) -> Optional[ObjectId]:
    try:
        return ObjectId(str(s))
    except Exception:
        return None
    

def _parse_bool(v: Optional[str]) -> Optional[bool]:
    if v is None:
        return None
    s = v.strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _parse_sort(sort: Optional[str]) -> List[Tuple[str, int]]:
    if not isinstance(sort, str) or ":" not in sort:
        return [("created_at", DESCENDING)]
    field, direction = sort.split(":", 1)
    field = field.strip()
    direction = direction.strip().lower()
    if field not in _ALLOWED_SORT_FIELDS:
        field = "created_at"
    order = ASCENDING if direction == "asc" else DESCENDING
    return [(field, order)]


def _page_args(args) -> Tuple[int, int]:
    try:
        p = int(args.get("page", 1))
        s = int(args.get("size", 20))
    except ValueError:
        return 1, 20
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > 100:
        s = 100
    return p, s


def _slugify_ko(text: str) -> str:
    t = (text or "").strip().lower()
    # allow hangul, numbers, ascii letter; replace others with hyphen
    t = re.sub(r"[^\uac00-/ud7a3a-z0-9]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-")
    return t or "news"


def _ensure_unique_slug(base: str, exclude_id: Optional[ObjectId] = None) -> str:
    col = _news()
    slug = base
    n = 1
    while True:
        q: Dict[str, Any] = {"slug": slug}
        if exclude_id:
            q["_id"] = {"$ne": exclude_id}
        if col.count_documents(q) == 0:
            return slug
        n += 1
        slug = f"{base}-{n}"


def _require_i18n(obj: Any, key: str) -> Dict[str, str]:
    if not isinstance(obj, dict):
        raise ValueError(f"{key} must be object")
    out: Dict[str, str] = {}
    for k in ("ko", "en"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
    if "ko" not in out:
        raise ValueError(f"{key}.ko required")
    return out


def _parse_iso_utc(s: str) -> datetime:
    if not isinstance(s, str) or not s:
        raise ValueError("invalid datetime")
    try:
        if s.endswith("Z"):
            base = datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        else:
            base = datetime.fromisoformat(s)
            if base.tzinfo is None:
                base = base.replace(tzinfo=timezone.utc)
            else:
                base = base.astimezone(timezone.utc)
        return base
    except Exception as e:
        raise ValueError("invalid datetime") from e
    

def _news():
    return get_collection("news")


@bp.get("/")
@apply_rate_limit
@require_admin
def list_news_admin():
    args = request.args
    page, size = _page_args(args)
    sort = args.get("sort", "created_at:desc")
    qtext = (args.get("q") or "").strip()
    status = (args.get("status") or "").strip().lower()
    filt: Dict[str, Any] = {}
    if qtext:
        rx = {"$regex": qtext, "$options": "i"}
        filt["$or"] = [
            {"title_i18m.ko": rx},
            {"title_i18n.en": rx},
            {"body_i18n.ko":rx},
            {"body_i18n.en", rx}
        ]
    if status:
        if status not in NEWS_ALLOWED_STATUS:
            return _err("ERR_INVALID_PAYLOAD", "invalid status")
        filt["status"] = status

    try:
        total = _news().count_documents(filt)
        cursor = (
            _news()
            .find(filt)
            .sort(_parse_sort(sort))
            .skip((page - 1) * size)
            .limit(size)
        )
        items: List[Dict[str, Any]] = []
        for d in cursor:
            d["_id"] = str(d["_id"])
            items.append(d)
        return _ok({"items": items, "total": int(total), "page": int(page), "size": int(size)})
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.post("/")
@apply_rate_limit
@require_admin
@csrf_protect
def create_news_admin():
    body = request.get_json(silent=True) or {}
    try:
        title_i18n = _require_i18n(body.get("title_i18n"), "title_i18n")
        body_i18n = _require_i18n(body.get("body_i18n"), "body_i18n")
        slug = (body.get("slug") or "").strip()
        if not slug:
            slug = _slugify_ko(title_i18n.get("ko", ""))
        slug = _ensure_unique_slug(slug)
        status = (body.get("status") or "draft").strip().lower()
        if status not in NEWS_ALLOWED_STATUS:
            raise ValueError("invalid status")
        thumbnail = body.get("thumbnail")
        published_at = body.get("published_at")
        pub_iso: Optional[str] = None
        if published_at:
            pub_dt = _parse_iso_utc(published_at)
            pub_iso = isoformat_utc(pub_dt)
        now_iso = isoformat_utc(now_utc())
        doc = {
            "slug": slug,
            "title_i18n": title_i18n,
            "body_i18n": body_i18n,
            "thumbnail": thumbnail if isinstance(thumbnail, str) and thumbnail.strip() else None,
            "status": status,
            "published_at": pub_iso,
            "created_at": now_iso,
            "updated_at": now_iso
        }
    except ValueError as e:
        return _err("ERR_INVALID_PAYLOAD", str(e))
    
    try:
        _news().insert_one(doc)
        doc["_id"] = str(doc.get("_id") or "")
        return _ok(doc, 201)
    except PyMongoError as e:
        m = map_pymongo_error(e)
        if m["code"] == "ERR_CONFLICT":
            # slug unique conflicts if there's an index
            return _err("ERR_CONFLICT", m["message"])
        return _err(m["code"], m["message"])
    

@bp.get("/<news_id>")
@apply_rate_limit
@require_admin
def get_news_admin(news_id: str):
    oid = _oid(news_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    try:
        d = _news().find_one({"_id": oid})
        if not d:
            return _err("ERR_NOT_FOUND", "news not found")
        d["_id"] = str(d["_id"])
        return _ok(d)
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.put("/<news_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def update_news_admin(news_id: str):
    oid = _oid(news_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    body = request.get_json(silent=True) or {}
    set_fields: Dict[str, Any] = {}
    try:
        if "title_i18n" in body:
            set_fields["title_i18n"] = _require_i18n(body.get("title_i18n"), "title_i18n")
        if "body_i18n" in body:
            set_fields["body_i18n"] = _require_i18n(body.get("body_i18n"), "body_i18n")
        if "thumbnail" in body:
            thumb = body.get("thumbnail")
            if thumb is not None and not isinstance(thumb, str):
                return _err("ERR_INVALID_PAYLOAD", "thumbnail must be string")
            set_fields["thumbnail"] = thumb if isinstance(thumb, str) and thumb.strip() else None
        if "status" in body:
            st = (body.get("status") or "").strip().lower()
            if st and st not in NEWS_ALLOWED_STATUS:
                return _err("ERR_INVALID_PAYLOAD", "invalid status")
            if st:
                set_fields["status"] = st
        if "slug" in body:
            raw = (body.get("slug") or "").strip()
            if not raw:
                return _err("ERR_INVALID_PAYLOAD", "slug required")
            base = _slugify_ko(raw)
            set_fields["slug"] = _ensure_unique_slug(base, exclude_id=oid)
        if "published_at" in body:
            pa = body.get("published_at")
            if pa is None:
                set_fields["published_at"] = None
            else:
                set_fields["published_at"] = isoformat_utc(_parse_iso_utc(pa))
    except ValueError as e:
        return _err("ERR_INVALID_PAYLOAD", str(e))
    
    if not set_fields:
        return _err("ERR_INVALID_PAYLOAD", "no fields to update")
    set_fields["updated_at"] = isoformat_utc(now_utc())
    try:
        doc = _news().find_one_and_update(
            {"_id": oid},
            {"$set": set_fields},
            return_document=ReturnDocument.AFTER
        )
        if not doc:
            return _err("ERR_NOT_FOUND", "news not found")
        doc["_id"] = str(doc["_id"])
        return _ok(doc)
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.patch("/<news_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def patch_news_admin(news_id: str):
    oid = _oid(news_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    body = request.get_json(silent=True) or {}
    op = (body.get("op") or "").strip().lower()
    if op not in {"schedule", "publish", "unpublish", "set_thumbnail"}:
        return _err("ERR_INVALID_PAYLOAD", "invalid op")
    
    update: Dict[str, Any] = {}
    if op == "schedule":
        published_at = body.get("published_at")
        if not isinstance(published_at, str) or not published_at.strip():
            return _err("ERR_INVALID_PAYLOAD", "published_at required")
        try:
            dt = _parse_iso_utc(published_at)
        except ValueError:
            return _err("ERR_INVALID_PAYLOAD", "invalid published_at")
        # scheduled if future, otherwise published
        status = "scheduled" if dt > now_utc() else "published"
        update = {"$set": {"published_at": isoformat_utc(dt), "status": status}}
    elif op == "publish":
        now_iso = isoformat_utc(now_utc())
        update = {"$set": {"status": "published", "published_at": now_iso}}
    elif op == "unpublish":
        update = {"$set": {"status": "draft"}, "$unset": {"published_at": ""}}
    elif op == "set_thumbnail":
        thumb = body.get("thumbnail")
        if not isinstance(thumb, str) or not thumb.strip():
            return _err("ERR_INVALID_PAYLOAD", "thumbnail required")
        update = {"$set": {"thumbnail": thumb.strip()}}
    
    # always bump updated_at
    if "$set" not in update:
        update["$set"] = {}
    update["$set"]["updated_at"] = isoformat_utc(now_utc())

    try:
        doc = _news().find_one_and_update(
            {"_id": oid},
            update,
            return_document=ReturnDocument.AFTER
        )
        if not doc:
            return _err("ERR_NOT_FOUND", "news not found")
        doc["_id"] = str(doc["_id"])
        return _ok(doc)
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.delete("/<news_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def delete_news_admin(news_id: str):
    oid = _oid(news_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    try:
        res = _news().delete_one({"_id": oid})
        if not res.acknowledged or res.deleted_count == 0:
            return _err("ERR_NOT_FOUND", "news not found")
        return _ok({"deleted": True})
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    