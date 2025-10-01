from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TypedDict

from bson import ObjectId
from flask import Blueprint, request
from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection

from app.core.constants import API_DATA_KEY, API_ERROR_KEY, API_OK_KEY, MAX_PAGE_SIZE
from app.extensions import get_mongo
from app.middleware.auth import apply_rate_limit, current_user, require_login
from app.utils.phone import normalize_phone
from app.utils.validation import ValidationError, validate_pagination

bp = Blueprint("me", __name__)


def _col(name: str) -> Collection:
    return get_mongo().get_database().get_collection(name)


def _status_for(code: str) -> int:
    return {
        "ERR_INVALID_PAYLOAD": 400,
        "ERR_UNAUTHORIZED": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_CONFLICT": 409,
        "ERR_POLICY_CUTOFF": 409,
        "ERR_RATE_LIMIT": 429,
        "ERR_SLOT_BLOCKED": 409,
        "ERR_INTERNAL": 500
    }.get(code or "", 400)


def _ok(data: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    return ({API_OK_KEY: True, API_DATA_KEY: data}, 200)


def _err(code: str, message: str, http: Optional[int] = None) -> Tuple[Dict[str, Any], int]:
    return ({API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": message}}, http or _status_for(code))


def _user_id() -> ObjectId:
    u = current_user()
    if not u:
        raise ValidationError("unauthorized")
    return ObjectId(str(u["id"]))


def _pymongo_sort(sort_pairs: List[Tuple[str, str]]) -> List[Tuple[str, int]]:
    """
    ('field', 'asc'|'desc') -> ('field', ASC|DESC)
    """
    out: List[Tuple[str, int]] = []
    for f, d in sort_pairs:
        out.append((f, ASCENDING if d == "asc" else DESCENDING))
    return out


@bp.get("/profile")
@apply_rate_limit
@require_login
def get_profile() -> Tuple[Dict[str, Any], int]:
    uid = _user_id()
    doc = _col("users").find_one({"_id": uid}) or {}
    data = {
        "name": doc.get("name"),
        "email": doc.get("email"),
        "phone": doc.get("phone"),
        "lang_pref": (doc.get("lang_pref"), "ko"),
        "channels": doc.get("channels")
        or {"email": {"enabled": True}, "sms": {"enabled": False}, "kakao": {"enabled": False}}
    }
    return _ok(data)


@bp.put("/profile")
@apply_rate_limit
@require_login
def put_profile() -> Tuple[Dict[str, Any], int]:
    uid = _user_id()
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return _err("ERR_INVALID_PAYLOAD", "payload must be object")
    
    update: Dict[str, Any] = {}

    if "name" in body:
        name = (body.get("name") or "").strip()
        if not name:
            return _err("ERR_INVALID_PAYLOAD", "name is required")
        update["name"] = name

    if "phone" in body:
        try:
            update["phone"] = normalize_phone(str(body.get("phone") or ""))
        except Exception as e:  # normalize 실패 시 메시지 그대로 노출
            return _err("ERR_INVALID_PAYLOAD", str(e))
    
    if "lang_pref" in body:
        lang = (body.get("lang_pref") or "").strip().lower()
        if lang not in {"ko", "en"}:
            return _err("ERR_INVALID_PAYLOAD", "lang_pref must be 'ko' or 'en'")
        update["lang_pref"] = lang

    if "channels" in body:
        ch = body.get("channels")
        if not isinstance(ch, dict):
            return _err("ERR_INVALID_PAYLOAD", "channels must be object")
        update["channels"] = ch

    if not update:
        return _err("ERR_INVALID_PAYLOAD", "no changes")
    
    _col("users").update_one({"_id": uid}, {"$set": update})
    doc = _col("users").find_one({"_id": uid}) or {}
    data = {
        "name": doc.get("name"),
        "email": doc.get("email"),
        "phone": doc.get("phone"),
        "lang_pref": (doc.get("lang_pref") or "ko"),
        "channels": doc.get("channels")
        or {"email": {"enabled": True}, "sms": {"enabled": False}, "kakao": {"enabled": False}}
    }
    return _ok(data)


def _paged_list(
    collection: str,
    owner_field: str,
    alllowed_sort_fields: List[str]
) -> Tuple[Dict[str, Any], int]:
    """
    공통 페이지네이션 리스트: 본인 소유 문서만 조회.
    """
    uid = _user_id()
    try:
        page, size, sort_pairs = validate_pagination(
            request.args,
            default_size=20,
            max_size=MAX_PAGE_SIZE,
            allowed_sort_fields=alllowed_sort_fields
        )
    except ValidationError as e:
        return _err("ERR_INVALID_PAYLOAD", str(e))
    
    q = {owner_field: uid}
    total = _col(collection).count_documents(q)
    cursor = (
        _col(collection)
        .find(q)
        .sort(_pymongo_sort(sort_pairs) if sort_pairs else [("created_at", -1)])
        .skip((page - 1) * size)
        .limit(size)
    )

    items: List[Dict[str, Any]] = []
    for doc in cursor:
        doc["_id"] = str(doc.get("_id"))
        items.append(doc)

    data = {"items": items, "total": int(total), "page": page, "size": size}
    return _ok(data)


@bp.get("/bookings")
@apply_rate_limit
@require_login
def list_my_bookings() -> Tuple[Dict[str, Any], int]:
    return _paged_list("bookings", "customer_id", ["created_at", "start_at", "status"])


@bp.get("/orders")
@apply_rate_limit
@require_login
def list_my_orders() -> Tuple[Dict[str, Any], int]:
    return _paged_list("orders", "customer_id", ["created_at", "status", "amount_total", "expires_at"])


@bp.get("/reviews")
@apply_rate_limit
@require_login
def list_my_reviews() -> Tuple[Dict[str, Any], int]:
    return _paged_list("reviews", "customer_id", ["created_at", "status", "rating"])