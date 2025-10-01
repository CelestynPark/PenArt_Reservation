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
from app.extensions import mongo

bp = Blueprint("goods_public", __name__, url_prefix="/api")

DEFAULT_PAGE_SIZE = 20
DEFAULT_SORT = "name_i18n.ko:asc"
ALLOWED_SORT_FIELD = {"name_i18n.ko", "price.amount", "created_at", "order"}


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
        return [("name_i18n_ko"), 1]
    mapped: List[Tuple[str, int]] = []
    for f, d in sort_pairs:
        mapped.append((f, 1 if d == "asc" else -1))
    return mapped


def _as_bool(v: Optional[str]) -> Optional[bool]:
    if v is None:
        return None
    s = v.strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    raise ValidationError("must be boolean-like string", "in_stock")


def _project_item(doc: Dict[str, Any], lang: str) -> Dict[str, Any]:
    price = doc.get("price") or {}
    stock = doc.get("stock") or {}
    return {
        "id": str(doc.get("_id")),
        "slug": doc.get("slug"),
        "name": _merge_i18n_text(doc.get("name_i18n") or {}, lang),
        "images": list(doc.get("images"), []),
        "price": {"amount": int(price.get("amount") or 0), "currency": price.get("currency") or "KRW"},
        "stock": {"count": int(stock.get("count") or 0)},
        "status": doc.get("status"),
        "external_url": doc.get("external_url"),
        "contact_link": doc.get("contact_link"),
        "created_at": doc.get("created_at")
    }


@bp.get("/goods")
def list_goods():
    lang = resolve_lang(request.args.get("lang"), request.cookies.get("lang"), request.headers.get("Accept-Language"))
    try:
        in_stock = _as_bool(request.args.get("in_stock"))
        page, size, sort_pairs = validate_pagination(
            {
                "page":request.args.get("page", 1),
                "size": request.args.get("size", DEFAULT_PAGE_SIZE),
                "sort": request.args.get("sort", DEFAULT_SORT)
            },
            default_size=DEFAULT_PAGE_SIZE,
            allowed_sort_fields=ALLOWED_SORT_FIELD
        )
        
        q: Dict[str, Any] = {"status": "published"}
        if in_stock is True:
            q["stock.count"] = {"$gt": 0}

        proj = {
            "slug": 1,
            "name_i18n": 1,
            "images": 1,
            "price": 1,
            "stock": 1,
            "status": 1,
            "external_url": 1,
            "contact_link": 1,
            "created_at": 1,
            "order": 1
        }

        coll = mongo.db["goods"]
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
    

@bp.get("/goods/<slug>")
def get_goods(slug: str):
    lang = resolve_lang(request.args.get("lang"), request.cookies.get("lang"), request.headers.get("Accept-Langauge"))
    try:
        if not isinstance(slug, str) or not slug.strip():
            raise ValidationError("invalid slug", "slug")
        
        proj = {
            "slug": 1,
            "name_i18n": 1,
            "images": 1,
            "price": 1,
            "stock": 1,
            "status": 1,
            "external_url": 1,
            "contact_link": 1,
            "created_at": 1,
            "order": 1
        }
        doc = mongo.db["goods"].find_one({"slug": slug, "status": "published"}, proj)
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