from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from flask import Blueprint, jsonify, request

from app.core.constants import (
    API_DATA_KEY,
    API_ERROR_KEY,
    API_I18N_KEY,
    API_OK_KEY,
    ErrorCode
)
from app.models.work import collection_name as WORKS_COLLECTION
from app.services.i18n_service import resolve_lang
from app.utils.validation import ValidationError, validate_enum, validate_pagination
from app.extensions import mongo

bp = Blueprint("gallery_public", __name__, url_prefix="/api")

# Endpoint-local defaults (do not change global pagination constants)
DEFAULT_PAGE_SIZE = 24
ALLOWED_SORT_FIELD = {"order", "created_at"}


def _status_from_code(code: str) -> int:
    if code == ErrorCode.ERR_INVALID_PAYLOAD.value:
        return 400
    if code == ErrorCode.ERR_UNAUTHORIZED.value:
        return 401
    if code == ErrorCode.ERR_FORBIDDEN.value:
        return 403
    if code == ErrorCode.ERR_NOT_FOUND.value:
        return 404
    if code == ErrorCode.ERR_CONFLICT.value:
        return 409
    if code == ErrorCode.ERR_RATE_LIMIT.value:
        return 4029
    return 500


def _with_lang(envelope: Dict[str, Any], lang: str) -> Dict[str, Any]:
    envelope[API_I18N_KEY] = {"lang": lang}
    return envelope


def _merge_i18n_text(obj: Optional[Dict[str, Any]], lang: str) -> str:
    if not isinstance(obj, dict):
        return ""
    val = obj.get(lang)
    if isinstance(val, str) and val.strip():
        return val
    ko = obj.get("ko")
    return ko if isinstance(ko, str) else ""


def _project_view(doc: Dict[str, Any], lang: str) -> Dict[str, Any]:
    return {
        "id": str(doc.get("_id")),
        "author_type": doc.get("author_type"),
        "title": _merge_i18n_text(doc.get("title_i18n") or {}, lang),
        "description": _merge_i18n_text(doc.get("description_i18n") or {}, lang),
        "images": list(doc.get("images") or []),
        "tags": list(doc.get("tags") or []),
        "is_visible": bool(doc.get("is_visible", True)),
        "order": int(doc.get("order") or 0),
        "created_at": doc.get("created_at") # already ISO8601 (UTC) per model/base
    }


def _build_sort(sort_pairs: List[Tuple[str, str]]) -> List[Tuple[str, int]]:
    if not sort_pairs:
        return [("order", 1)]
    mapped: List[Tuple[str, int]] = []
    for f, d in sort_pairs:
        mapped.append((f, 1 if d == "asc" else -1))
    return mapped


@bp.get("/gallery")
def list_gallery():
    lang = resolve_lang(request.args.get("lang"), request.cookies.get("lang"), request.headers.get("Accept-Language"))
    try:
        # Filters
        author = request.args.get("author")
        if author:
            validate_enum(author, {"artist", "student"}, "author")

        tag = request.args.get("tag")
        search = request.args.get("search")

        # Pagination & sort
        page, size, sort_pairs = validate_pagination(
            {
                "page": request.args.get("page", 1),
                "size": request.args.get("size", DEFAULT_PAGE_SIZE),
                "sort": request.args.get("sort", "order:asc")
            },
            default_size=DEFAULT_PAGE_SIZE,
            allowed_sort_fields=ALLOWED_SORT_FIELD
        )

        # Query
        q: Dict[str, Any] = {"is_visible": True}
        if author:
            q["author_type"] = author
        if tag:
            q["tags"] = tag
        if search:
            rx = {"$regex": search, "$options": "i"}
            q["$or"] = [
                {"title_i18n.ko": rx},
                {"title_i18n.en": rx},
                {"description_i18n.ko": rx},
                {"description_i18n.en": rx},
                {"tags": rx}
            ]

        coll = mongo.db[WORKS_COLLECTION]
        total = coll.count_documents(q)
        cur = (
            coll.find(
                q,
                {
                    "author_type": 1,
                    "title_i18n": 1,
                    "description_i18n": 1,
                    "images": 1,
                    "tags": 1,
                    "is_visible": 1,
                    "order": 1,
                    "created_at": 1
                },
            )
            .sort(_build_sort(sort_pairs))
            .skip((page - 1) * size)
            .limit(size)
        )

        items = [_project_view(doc, lang) for doc in cur]
        body = _with_lang(
            {API_OK_KEY: True, API_DATA_KEY: {"items": items, "total": int(total), "page": page, "size": size}},
            lang
        )
        return jsonify(body)
    except ValidationError as ve:
        body = _with_lang(
            {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INVALID_PAYLOAD.value, "message": str(ve)}},
            lang
        )
        return jsonify(body), 400
    except Exception:
        body = _with_lang(
            {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INTERNAL.value, "message": "internal error"}}, lang
        )
        return jsonify(body), 500
    

@bp.get("/gallery/<id>")
def get_gallery_item(id: str):
    lang = resolve_lang(request.args.get("lang"), request.cookies.get("lang"), request.headers.get("Accept-Language"))
    try:
        try:
            oid = ObjectId(id)
        except Exception as e:
            raise ValidationError("invalid id format", "id") from e
        
        doc = mongo.db[WORKS_COLLECTION].find_one(
            {"_id": oid, "is_visible": True},
            {
                "author_type": 1,
                "title_i18n": 1,
                "description_i18n": 1,
                "images": 1,
                "tags": 1,
                "is_visible": 1,
                "order": 1,
                "created_at": 1 
            },
        )
        if not doc:
            body = _with_lang(
                {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_NOT_FOUND.value, "message": "not found"}},
                lang
            )
            return jsonify(body), 404
        
        body = _with_lang({API_OK_KEY: True, API_DATA_KEY: _project_view(doc, lang)}, lang)
        return jsonify(body)
    except ValidationError as ve:
        body = _with_lang(
            {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INVALID_PAYLOAD.value, "message": str(ve)}},
            lang
        )
        return jsonify(body), 400
    except Exception:
        body = _with_lang(
            {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INTERNAL.value, "message": "internal error"}}, lang
        )
        return jsonify(body), 500
    