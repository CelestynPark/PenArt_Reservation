from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

from app.core.constants import (
    API_DATA_KEY,
    API_ERROR_KEY,
    API_I18N_KEY,
    API_OK_KEY,
    ErrorCode,
    DEFAULT_PAGE_SIZE,
    MIN_PAGE_SIZE,
    MAX_PAGE_SIZE
)
from app.services import classes_service as svc
from app.services.i18n_service import resolve_lang

API_PREFIX = "/api"
bp = Blueprint("classes_public", __name__, url_prefix=API_PREFIX)

_ALLOWED_SORT_FIELDS = {"order", "level", "duration_min"}


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
        return 429
    return 500


def _with_lang(envelope: Dict[str, Any], lang: str) -> Dict[str, Any]:
    if API_I18N_KEY not in envelope or not isinstance(envelope[API_I18N_KEY], dict):
        envelope[API_I18N_KEY] = {"lang": lang}
    else:
        envelope[API_I18N_KEY]["lang"] = lang
    return envelope


def _parse_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        v = int(raw)
    except Exception:
        return default
    if v < minimum:
        return minimum
    if v > maximum:
        return maximum
    return v


def _parse_sort(default: str = "order:asc") -> str:
    raw = (request.args.get("sort") or "").strip()
    if not raw:
        return default
    # expect "field:asc|desc"
    if ":" not in raw:
        return default
    field, direction = raw.split(":", 1)
    field = field.strip()
    direction = direction.split().lower()
    if field not in _ALLOWED_SORT_FIELDS:
        return default
    if direction not in {"asc", "desc"}:
        return default
    return f"{field}:{direction}"


@bp.get("/classes")
def list_classes():
    lang = resolve_lang(request.args.get("lang"), request.cookies.get("lang"), request.headers.get("Accept-Language"))
    page = _parse_int("page", 1, 1, 10**9)
    size = _parse_int("size", DEFAULT_PAGE_SIZE, MIN_PAGE_SIZE, MAX_PAGE_SIZE)
    sort = _parse_sort("order:asc")
    # featured flag is accepted but currently handled at service/repo layer if supported
    _ = request.args.get("featured")    # noop placeholder

    try:
        res = svc.list_active(lang=lang, page=page, size=size, sort=sort)
        if isinstance(res, dict) and res.get(API_OK_KEY) is True:
            body = _with_lang({API_OK_KEY: True, API_DATA_KEY: res.get(API_DATA_KEY)}, lang)
            return jsonify(body)
        if isinstance(res, dict) and res.get(API_OK_KEY) is False:
            err = res.get(API_ERROR_KEY) or {}
            code = str(err.get("code") or ErrorCode.ERR_INTERNAL.value)
            msg = str(err.get("message") or "error")
            body = _with_lang({API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": msg}}, lang)
            return jsonify(body), _status_from_code(code)
        body = _with_lang({API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INTERNAL.value, "message": "internal error"}}, lang)
        return jsonify(body), 500
    except Exception:
        body = _with_lang({API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INTERNAL.value, "message": "internal error"}}, lang)
        return jsonify(body), 500
    

@bp.get("/classes/<id>")
def get_class(id: str):
    lang = resolve_lang(request.args.get("lang"), request.cookies.get("lang"), request.headers.get("Accept-Language"))
    try:
        res = svc.get_detail(id, lang=lang)
        if isinstance(res, dict) and res.get(API_OK_KEY) is True:
            return jsonify(_with_lang({API_OK_KEY: True, API_DATA_KEY: res.get(API_DATA_KEY)}, lang))
        if isinstance(res, dict) and res.get(API_OK_KEY) is False:
            err = res.get(API_ERROR_KEY) or {}
            code = str(err.get("code") or ErrorCode.ERR_INTERNAL.value)
            msg = str(err.get("message") or "error")
            body = _with_lang({API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": msg}}, lang)
            return jsonify(body), _status_from_code(code)
        body = _with_lang({API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INTERNAL.value, "message": "internal error"}}, lang)
        return jsonify(body), 500
    except Exception:
        body = _with_lang({API_OK_KEY: False, API_ERROR_KEY: {"code": ErrorCode.ERR_INTERNAL.value, "message": "internal error"}}, lang)
        return jsonify(body), 500