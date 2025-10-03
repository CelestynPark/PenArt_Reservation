from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from flask import Blueprint, request
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import PyMongoError

from app.middleware.auth import apply_rate_limit, csrf_protect, require_admin
from app.repositories.common import get_collection, map_pymongo_error
from app.services import goods_service  # build/runtime hard dep
from app.utils.time import isoformat_utc, now_utc

bp = Blueprint("admin_goods", __name__)

DEFAULT_PAGE_SIZE = 20
_ALLOWED_SORT_FIELDS = (
    "created_at",
    "updated_at",
    "name_i18n.ko",
    "price.amount",
    "stock.count",
    "status",
    "_id"
)
_ALLOWED_STATUS = {"draft", "published"}


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
    

def _ok(data: Any, status: int = 200) -> Tuple[Dict[str, Any], int]:
    return ({"ok": True, "data": data}, status)


def _err(code: str, message: str) -> Tuple[Dict[str, Any], int]:
    return ({"ok": False, "error": {"code": code, "message": message}}, _http_for(code))


def _goods():
    return get_collection("goods")


def _oid(s: str) -> Optional[ObjectId]:
    try:
        return ObjectId(str(s))
    except Exception:
        return None
    

def _page_args(args) -> Tuple[int, int]:
    try: 
        p = int(args.get("page", 1))
        s = int(args.get("size", DEFAULT_PAGE_SIZE))
    except ValueError:
        return 1, DEFAULT_PAGE_SIZE
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > 100:
        s = 100
    return p, s


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


def _require_images(v: Any) -> List[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("images must be array")
    out: List[str] = []
    for it in v:
        if not isinstance(it, str) or not it.strip():
            raise ValueError("images[] must be string")
        out.append(it.strip())
    return out


def _require_price(obj: Any) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("price must be object")
    amount = obj.get("amount")
    currency = obj.get("currency")
    if not isinstance(amount, int) or amount < 0:
        raise ValueError("price.amount must be integer >= 0")
    if currency != "KRW":
        raise ValueError("price.currency must be 'KRW'")
    return {"amount": int(amount), "currency": "KRW"}


def _require_stock(obj: Any) -> Dict[str, Any]:
    if not isinstance(obj, dict):
        raise ValueError("stock must be object")
    count = obj.get("count")
    allow_backorder = obj.get("allow_backorder")
    if not isinstance(count, int) or count < 0:
        raise ValueError("stock.count must be interer >= 0")
    if not isinstance(allow_backorder, bool):
        raise ValueError("stock.allow_backorder must be boolean")
    return {"count": int(count), "allow_backorder": bool(allow_backorder)}


def _opt_str(v: Any, key: str) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError(f"{key} must be string")
    s = v.strip()
    return s if s else None


def _sanitize_link(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    if not re.match(r"^https?://", s):
        # allow non-http link schemes? keep simple as per spec
        pass
    return s


def _serialize(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out["_id"] = str(doc.get("_id"))
    return out


@bp.get("/")
@apply_rate_limit
@require_admin
def list_goods_admin():
    args = request.args
    page, size = _page_args(args)
    sort = args.get("sort", "created_at:desc")
    qtext = (args.get("q") or "").strip()
    status = (args.get("status") or "").strip().lower()
    filt: Dict[str, Any] = {}
    if qtext:
        rx = {"$regex": qtext, "$options": "i"}
        filt["$or"] = [
            {"name_i18n.ko": rx},
            {"name_i18n.en": rx},
            {"description_i18n.ko": rx},
            {"description_i18n.en": rx}
        ]
    if status:
        if status not in _ALLOWED_STATUS:
            return _err("ERR_INVALID_PAYLOAD", "invalid status")
        filt["status"] = status
    try:
        total = _goods().count_documents(filt)
        cursor = (
            _goods()
            .find(filt)
            .sort(_parse_sort(sort))
            .skip((page - 1) * size)
            .limit(size)
        )
        items = [_serialize(d) for d in cursor]
        return _ok({"items": items, "total": int(total), "page": int(page), "size": int(size)})
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.post("/")
@apply_rate_limit
@require_admin
@csrf_protect
def create_goods_admin():
    body = request.get_json(silent=True) or {}
    try:
        name_i18n = _require_i18n(body.get("name_i18n"), "name_i18n")
        description_i18n = _require_i18n(body.get("description_i18n"), "description_i18n")
        images = _require_images(body.get("images"))
        price = _require_price(body.get("price"))
        stock = _require_stock(body.get("stock"))
        status = (body.get("status") or "draft").strip().lower()
        if status not in _ALLOWED_STATUS:
            raise ValueError("invalid status")
        contact_link = _sanitize_link(_opt_str(body.get("contact_link"), "contact_link"))
        external_url = _sanitize_link(_opt_str(body.get("external_url"), "external_url"))

        now_iso = isoformat_utc(now_utc())
        doc = {
            "name_i18n": name_i18n,
            "description_i18n": description_i18n,
            "images": images,
            "price": price,
            "stock": stock,
            "status": status,
            "contact_link": contact_link,
            "external_url": external_url,
            "created_at": now_iso,
            "updated_at": now_iso
        }
    except ValueError as e:
        return _err("ERR_INVALID_PAYLOAD", str(e))
    
    try:
        _goods().insert_one(doc)
        return _ok(_serialize(doc), 201)
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.get("/<goods_id>")
@apply_rate_limit
@require_admin
def get_goods_admin(goods_id: str):
    oid = _oid(goods_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    try:
        d = _goods().find_one({"_id": oid})
        if not d:
            return _err("ERR_NOT_FOUND", "goods not found")
        return _ok(_serialize(d))
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.put("/<goods_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def update_goods_admin(goods_id: str):
    oid = _oid(goods_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    body = request.get_json(silent=True) or {}
    set_fields = Dict[str, Any] = {}
    try:
        if "name_i18n" in body:
            set_fields["name_i18n"] = _require_i18n(body.get("name_i18n"), "name_i18n")
        if "description_i18n" in body:
            set_fields["description_i18n"] = _require_i18n(body.get("description_i18n"), "description_i18n")
        if "images" in body:
            set_fields["images"] = _require_images(body.get("images"))
        if "price" in body:
            set_fields["price"] = _require_price(body.get("price"))    
        if "stock" in body:
            set_fields["stock"] = _require_stock(body.get("stock"))
        if "status" in body:
            st = (body.get("status") or "").strip().lower()
            if st and st not in _ALLOWED_STATUS:
                return _err("ERR_INVALID_PAYLOAD", "invalid status")
            if st:
                set_fields["status"] = st
        if "contact_link" in body:
            set_fields["contact_link"] = _sanitize_link(body.get("contact_link"), "contact_link")
        if "external_url" in body:
            set_fields["external_url"] = _sanitize_link(body.get("external_url"), "external_url")
    except ValueError as e:
        return _err("ERR_INVALID_PAYLOAD", str(e))
    
    if not set_fields:
        return _err("ERR_INVALID_PAYLOAD", "no fields to update")
    set_fields["updated_at"] = isoformat_utc(now_utc())
    try:
        doc = _goods().find_one_and_update(
            {"_id": oid},
            {"$set": set_fields},
            return_document=ReturnDocument.AFTER
        )
        if not doc:
            return _err("ERR_NOT_FOUND", "goods not found")
        return _ok(_serialize(doc))
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.patch("/<goods_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def patch_goods_admin(goods_id: str):
    oid = _oid(goods_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    body = request.get_json(silent=True) or {}
    op = (body.get("op") or "").strip().lower()
    if op not in {"publish", "unpublish", "set_price", "set_stock", "set_links"}:
        return _err("ERR_INVALID_PAYLOAD", "invalid op")
    
    update: Dict[str, Any] = {}
    try:
        if op == "publish":
            update = {"$set": {"status": "published"}}
        if op == "unpublish":
            update = {"$set": {"status": "draft"}}
        if op == "set_price":
            price = _require_price(body.get("price"))
            update = {"$set": {"price": price}}
        if op == "set_stock":
            stock = _require_stock(body.get("stock"))
            update = {"$set": {"stock": stock}}
        elif op == "set_links":
            contact_link = _sanitize_link(_opt_str(body.get("contact_link"), "contact_link"))
            external_url = _sanitize_link(_opt_str(body.get("external_url"), "external_url"))
            update = {"$set": {"contact_link": contact_link, "external_url": external_url}}
    except ValueError as e:
        return _err("ERR_INVALID_PAYLOAD", str(e))
    
    if "$set" not in update:
        update["$set"] = {}
    update["$set"]["updated_at"] = isoformat_utc(now_utc())

    try:
        # Use goods_service import to ensrue hards dependency presence; admin ops are direct writes.
        _ =  goods_service.current_policy() # no-op usage for build/runtime
        doc = _goods().find_one_and_update(
            {"_id", oid},
            update,
            return_document=ReturnDocument.AFTER
        )
        if not doc:
            return _err("ERR_NOT_FOUND", "goods not found")
        return _ok(_serialize(doc))
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.delete("/<goods_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def delete_goods_admin(goods_id: str):
    oid = _oid(goods_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    try:
        res = _goods().delete_one({"_id": oid})
        if not res.acknowledged or res.deleted_count == 0:
            return _err("ERR_NOT_FOUND", "news not found")
        return _ok({"deleted": True})
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])