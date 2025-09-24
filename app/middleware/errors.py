from __future__ import annotations

import json
import logging
import traceback
import uuid
from typing import Any, Dict, Tuple

from flask import Response, current_app, g, request
from werkzeug.exceptions import HTTPException, BadRequest, Unauthorized, Forbidden, NotFound, Conflict, UnprocessableEntity, TooManyRequests

from app.utils.validation import ValidationError
from app.services.i18n_service import t

__all__ = ["register_error_handlers"]

_LOG = logging.getLogger(__name__)

_ERR_MAP: Dict[int, Tuple[str, str]] = {
    400: ("ERR_INVALID_PAYLOAD", "errors.invalid_payload"),
    401: ("ERR_UNAUTHORIZED", "errors.unauthorized"),
    403: ("ERR_FORBIDDEN", "errors.forbidden"),
    404: ("ERR_NOT_FOUND", "errors.not_found"),
    409: ("ERR_CONFLICT", "errors.conflict"),
    422: ("ERR_INVALID_PAYLOAD", "errors.unprocessable"),
    429: ("ERR_RATE_LIMIT", "errors.rate_limit"),
    500: ("ERR_INTERNAL", "errors.internal"),
}


def _req_id() -> str:
    hdr = request.headers.get("X-Request-Id")
    if hdr and hdr.strip():
        return hdr.strip()
    return uuid.uuid4().hex


def _lang() -> str:
    return getattr(g, "lang", None) or "ko"


def _mk_envelope(code_enum: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "error": {"code": code_enum, "message": message}, "i18n": {"lang": _lang()}}


def _respond(status: int, code_enum: str, msg_key: str, *, detail: str | None = None) -> Response:
    lang = _lang()
    msg = t(lang, msg_key)
    # If bundle missing, show a safe generic English fallback
    if msg == msg_key:
        _fallback: Dict[str, str] = {
            "errors.invalid_payload": "Invalid request payload.",
            "errors.unauthorized": "Unauthorized.",
            "errors.forbidden": "Forbidden.",
            "errors.not_found": "Not found.",
            "errors.conflict": "Conflict.",
            "errors.unprocessable": "Unprocessable entity.",
            "errors.rate_limit": "Rate limit exceeded.",
            "errors.internal": "Internal server error.",
        }
        msg = _fallback.get(msg_key, "Error.")
    if detail and current_app.debug:
        msg = f"{msg} ({detail})"

    body = json.dumps(_mk_envelope(code_enum, msg), ensure_ascii=False)
    resp = Response(body, status=status, mimetype="application/json")
    resp.headers["X-Request-Id"] = _req_id()
    return resp


def _handle_validation(err: ValidationError) -> Response:
    # Field-aware message exposure is okay; still mapped to 400
    detail = str(err)
    return _respond(400, *_ERR_MAP[400], detail=detail)


def _handle_http(err: HTTPException) -> Response:
    status = err.code or 500
    code_enum, key = _ERR_MAP.get(status, _ERR_MAP[500])
    # Prefer werkzeug description for debug detail
    detail = getattr(err, "description", None)
    return _respond(status, code_enum, key, detail=str(detail) if detail else None)


def _handle_generic(err: Exception) -> Response:
    # Log stack but hide internal detail from clients
    rid = _req_id()
    _LOG.error("Unhandled exception (rid=%s) %s\n%s", rid, err, traceback.format_exc())
    resp = _respond(500, *_ERR_MAP[500])
    resp.headers["X-Request-Id"] = rid
    return resp


def register_error_handlers(app) -> None:
    app.register_error_handler(ValidationError, _handle_validation)

    app.register_error_handler(BadRequest, _handle_http)
    app.register_error_handler(Unauthorized, _handle_http)
    app.register_error_handler(Forbidden, _handle_http)
    app.register_error_handler(NotFound, _handle_http)
    app.register_error_handler(Conflict, _handle_http)
    app.register_error_handler(UnprocessableEntity, _handle_http)
    app.register_error_handler(TooManyRequests, _handle_http)

    app.register_error_handler(HTTPException, _handle_http)
    app.register_error_handler(Exception, _handle_generic)
