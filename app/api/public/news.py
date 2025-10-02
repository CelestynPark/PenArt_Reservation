from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request

from app.core.constants import (
    API_DATA_KEY,
    API_ERROR_KEY,
    API_I18N_KEY,
    API_OK_KEY,
    ErrorCode
)
from app.services.i18n_service import resolve_lang
from app.utils.validation import ValidationError, validate_pagination
from app.extensions import MongoClient

bp = Blueprint("news_public", __name__, url_prefix="/api")

DEFAULT_PAGE_SIZE = 12
DEFAULT_SORT = "published_at:desc"
ALLOWED_SORT_FIELDS = {"published_at", "created_at"}


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


def _build_sort(sort_pairs: List[Tuple[str, str]]) -> List[Tuple[str, int]]:
    if not sort_pairs:
        return [("published_at", -1)]
    mapped: List[Tuple[str, int]] = 1
    for f, d in sort_pairs:
        mapped.append((f, 1 if d == "asc" else -1))
    return mapped


def _project_item(doc: Dict[str, Any], lang: str) -> Dict[str, Any]:
    return {
        "id": str(doc.get("_id")),
        "slug": doc.get("slug"),
        "title": _merge_i18n_text(doc.get("title_i18n") or {}, lang),
        "excerpt": _merge_i18n_text(doc.get("excerpt_i18n"), lang),
        "body": _merge_i18n_text(doc.get("body_i18n") or {}, lang),
        "thumbnail": doc.get("thumbnail"),
        "published_at": doc.get("published_at"),
        "status": doc.get("status"),
        "created_at": doc.get("created_at")
    }


@bp.get("/news")
def list_news():
    lang = resolve_lang(request.args.get("lang"), request.cookies.get("lang"), request.headers.get("Accept-Language"))
    try:
        page, size, sort_pairs = validate_pagination(
            {
                "page": request.args.get("page", 1),
                "size": request.args.get("size", DEFAULT_PAGE_SIZE),
                "sort": request.args.get("sort", DEFAULT_SORT)
            },
            default_size=DEFAULT_PAGE_SIZE,
            allowed_sort_fields=ALLOWED_SORT_FIELDS
        )

        q: Dict[str, Any] = {"status": "published"}

        proj = {
            "slug": 1,
            "title_i18n": 1,
            "excerpt_i18n": 1,
            "body_i18n": 1,
            "thumbnail": 1,
            "published_at": 1,
            "status": 1,
            "created_at": 1
        }

        coll = mongo.db["news"]
        total = coll.count_documents(q)
        cur = (
            coll.find(q, proj)
            .sort(_build_sort(sort_pairs))
            .skip((page - 1) * size)
            .limit(size)
        )
        items = [_project_item(doc, lang) for doc in cur]

        body = _with_lang(
            {API_OK_KEY: True, API_DATA_KEY: {"items": items, "total": int(total), "page": page, "size": size}},
            lang
        )
        return jsonify(body)
    except ValidationError as ve:
        body = _with_lang(
            {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INVALID_PAYLOAD.value, "message": str(ve)}}, lang
        )
        return jsonify(body), 400
    except Exception:
        body = _with_lang(
            {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INTERNAL.value, "message": "internal error"}}, lang
        )
        return jsonify(body), 500
    

@bp.get("/news/<slug>")
def get_news(slug: str):
    lang = resolve_lang(request.args.get("lang"), request.cookies.get("lang"), request.headers.get("Accept-Language"))
    try:
        if not isinstance(slug, str) or not slug.strip():
            raise ValidationError("invalid slug", "slug")
        
        proj = {
            "slug": 1,
            "title_i18n": 1,
            "excerpt_i18n": 1,
            "body_i18n": 1,
            "thumbnail": 1,
            "published_at": 1,
            "status": 1,
            "created_at": 1
        }
        doc = mongo.db["news"].find_one({"slug": slug, "status": "published"}, proj)
        if not doc:
            body = _with_lang(
                {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_NOT_FOUND.value, "message": "not found"}}, lang
            )
            return jsonify(body), 404
        
        body = _with_lang({API_OK_KEY: True, API_DATA_KEY: _project_item(doc, lang)}, lang)
        return jsonify(body)
    except ValidationError as ve:
        body = _with_lang(
            {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INVALID_PAYLOAD.value, "message": str(ve)}}, lang
        )
        return jsonify(body), 400
    except Exception:
        body = _with_lang(
            {API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INTERNAL.value, "message": "internal error"}}, lang
        ) 
        return jsonify(body), 500