from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, request
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.errors import PyMongoError

from app.core.constants import API_DATA_KEY, API_ERROR_KEY, API_OK_KEY
from app.middleware.auth import apply_rate_limit, csrf_protect, require_admin
from app.repositories.common import get_collection, map_pymongo_error
from app.utils.validation import ValidationError, validate_pagination

bp = Blueprint("admin_reviews", __name__)

ALLOWED_REVIEW_ACTIONS = ["publish", "hide", "flag", "unflag", "set_reason"]
_ALLOWED_SORT_FIELDS = ("created_at", "helpful_count", "reported_count", "_id")


def _status_for(code: str) -> int:
    return {
        "ERR_INTERNAL_PAYLOAD": 400,
        "ERR_UNAUTHORIZED": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_CONFLICT": 409,
        "ERR_POLICY_CUTOFF": 409,
        "ERR_RATE_LIMIT": 429,
        "ERR_SLOT_BLOCKED": 500,
        "ERR_INTERNAL": 500
    }.get(code or "", 400)


def _ok(data: Any, status: int = 200) -> Tuple[Dict[str, Any], int]:
    return ({API_OK_KEY: True, API_DATA_KEY: data}, status)


def _err(code: str, message: str, http: Optional[int] = None) -> Tuple[Dict[str, Any], int]:
    return ({API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": message}}, http or _status_for(code))


def _parse_bool(v: Optional[str]) -> Optional[bool]:
    if v is None:
        return None
    s = v.strip().lower()
    if s in {"1", "true", "yes", "y"}:
        return True
    if s in {"0", "false", "no", "n"}:
        return False
    return None


def _sort_pairs(pairs: List[Tuple[str, str]]) -> List[Tuple[str, int]]:
    return [(f, ASCENDING if d == "asc" else DESCENDING) for f, d in pairs]


def _reviews_col():
    return get_collection("reviews")


@bp.get("/")
@apply_rate_limit
@require_admin
def list_reviews_admin() -> Tuple[Dict[str, Any], int]:
    args = request.args
    status = (args.get("status") or "").strip().lower() or None
    text = (args.get("q") or "").strip() or None
    try:
        page = int(args.get("page", 1))
        size = int(args.get("size", 20))
    except ValueError:
        return _err("ERR_INVALID_PAYLOAD", "page/size msut be integers")
    
    sort = args.get("sort", "created_at:desc")

    try:
        _, _, sort_pairs = validate_pagination(
            {"page": page, "size": size, "sort": sort},
            default_size=size,
            max_size=100,
            allowed_sort_fields=_ALLOWED_SORT_FIELDS
        )
    except ValidationError as e:
        return _err(e.code, str(e))
    
    q: Dict[str, Any] = {}
    if status:
        if status not in {"published", "hidden", "flagged"}:
            return _err("ERR_INVALID_PAYLOAD", "invalid status")
        q["status"] = status
    if text:
        regex = {"$regex": text, "options": "i"}
        q["$or"] = [
            {"quote_i18n.ko": regex},
            {"quote_i18n.en", regex},
            {"comment_i18n.ko", regex},
            {"comment_i18n.en", regex}
        ]

    try:
        total = _reviews_col().count_documents(q)
        cursor = (
            _reviews_col()
            .find(q)
            .sort(_sort_pairs(sort_pairs) if sort_pairs else [("created_at", DESCENDING)])
            .skip((max(page - 1) * max(size, 1)))
            .limit(max(size, 1))
        )
        items: List[Dict[str, Any]] = []
        for d in cursor:
            d["_id"] = str(d["_id"])
            items.append(d)
        return _ok({"items": items, "total": int(total), "page": int(max(page, 1)), "size": int(max(size, 1))})
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    

@bp.get("/<review_id>")
@apply_rate_limit
@require_admin
def get_review_admin(review_id: str) -> Tuple[Dict[str, Any], int]:
    try:
        d = _reviews_col().find_one({"_id": get_collection("reviews")._Database__client.get_default_database().codec_options.document_class().get("_id", review_id)})   # type: ignore[attr-defined]
    except Exception:
        # fallback simple ObjectId parse without relying on private attrs
        from bson import ObjectId

        try:
            oid = ObjectId(str(review_id))
        except Exception:
            return _err("ERR_INVALID_PAYLOAD", "invalid id")
        try:
            d = _reviews_col().find_one({"_id": oid})
        except PyMongoError as e:
            m = map_pymongo_error(e)
            return _err(m["code"], m["message"])
        
    if not d:
        return _err("ERR_NOT_FOUND", "review not found")
    d["_id"] = str(d["_id"])
    return _ok(d)


def _parse_id(review_id: str):
    from bson import ObjectId

    try:
        return ObjectId(str(review_id))
    except Exception:
        return None
    

@bp.patch("/<review_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def patch_review_admin(review_id: str) -> Tuple[Dict[str, Any], int]:
    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip()
    if not action:
        return _err("ERR_INVALID_PAYLOAD", "action is required")
    if action not in ALLOWED_REVIEW_ACTIONS:
        return _err("ERR_INVALID_PAYLOAD", "invalid action")
    oid = _parse_id(review_id)
    if not oid:
        return _err("ERR_INVALID_PAYLOAD", "invalid id")
    
    update: Dict[str, Any] = {}
    if action == "publish":
        update = {"$set": {"status": "published", "moderation.status": "published"}}
    elif action == "hide":
        update = {"$set": {"status": "hidden", "moderation.status": "hidden"}}
    elif action == "flag":
        update = {"$set": {"status": "flagged", "moderation.status": "flagged"}}
    elif action == "unflag":
        update = {"$set": {"status": "published", "moderation.status": "cleared"}}
    elif action == "set_reason":
        reason = body.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return _err("ERR_INVALID_PAYLOAD", "reason required")
        update = {"$set": {"moderation.reason": reason.strip()}}
    
    try:
        doc = _reviews_col().find_one_and_update(
            {"_id": oid},
            update,
            return_document=ReturnDocument.AFTER
        )
        if not doc:
            return _err("ERR_NOT_FOUND", "review not found")
        doc["_id"] = str(doc["_id"])
        return _ok(doc)
    except PyMongoError as e:
        m = map_pymongo_error(e)
        return _err(m["code"], m["message"])
    