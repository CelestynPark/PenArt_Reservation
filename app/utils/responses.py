from __future__ import annotations

from typing import Any, Dict, Tuple, Type

from flask import Response, jsonify
from werkzeug.exceptions import HTTPException, BadRequest, Unauthorized, Forbidden, NotFound, Conflict, TooManyRequests, InternalServerError

from app.core.constants import (
    ERR_CONFLICT,
    ERR_FORBIDDEN,
    ERR_INTERNAL,
    ERR_INVALID_PAYLOAD,
    ERR_NOT_FOUND,
    ERR_RATE_LIMIT,
    ERR_UNAUTHORIZED,
    ERROR_CODES,
)


def _json(status: int, payload: Dict[str, Any]) -> Response:
    resp = jsonify(payload)
    resp.status_code = status
    return resp


def ok(data: Any = None, lang: str | None = None) -> Response:
    body: Dict[str, Any] = {"ok": True}
    if data is not None:
        body["data"] = data
    if lang:
        body["i18n"] = {"lang": lang}
    return _json(200, body)


def err(code: str, message: str, status: int = 400, lang: str | None = None) -> Response:
    if code not in ERROR_CODES:
        code = ERR_INTERNAL
        status = 500
    body: Dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if lang:
        body["i18n"] = {"lang": lang}
    return _json(status, body)


# --- Exception → (status, code, message) mapping ---


_HTTP_TO_CODE: Dict[Type[HTTPException], str] = {
    BadRequest: ERR_INVALID_PAYLOAD,
    Unauthorized: ERR_UNAUTHORIZED,
    Forbidden: ERR_FORBIDDEN,
    NotFound: ERR_NOT_FOUND,
    Conflict: ERR_CONFLICT,
    TooManyRequests: ERR_RATE_LIMIT,
    InternalServerError: ERR_INTERNAL,
}


def _map_http_exc(e: HTTPException) -> Tuple[int, str, str]:
    status = getattr(e, "code", 500) or 500
    code = ERR_INTERNAL
    for etype, c in _HTTP_TO_CODE.items():
        if isinstance(e, etype):
            code = c
            break
    # Fallback by family
    if code == ERR_INTERNAL:
        if 400 <= status < 500:
            code = ERR_INVALID_PAYLOAD
        if status == 401:
            code = ERR_UNAUTHORIZED
        elif status == 403:
            code = ERR_FORBIDDEN
        elif status == 404:
            code = ERR_NOT_FOUND
        elif status == 409:
            code = ERR_CONFLICT
        elif status == 429:
            code = ERR_RATE_LIMIT
    message = getattr(e, "description", str(e)) or "error"
    return status, code, message


def map_exception(exc: BaseException) -> Tuple[int, str, str]:
    if isinstance(exc, HTTPException):
        return _map_http_exc(exc)
    if isinstance(exc, PermissionError):
        return 403, ERR_FORBIDDEN, str(exc) or "forbidden"
    if isinstance(exc, FileNotFoundError):
        return 404, ERR_NOT_FOUND, str(exc) or "not found"
    if isinstance(exc, KeyError):
        return 400, ERR_INVALID_PAYLOAD, "missing or invalid field"
    if isinstance(exc, ValueError):
        return 400, ERR_INVALID_PAYLOAD, str(exc) or "invalid payload"
    return 500, ERR_INTERNAL, str(exc) or "internal error"


def handle_exception(exc: BaseException, lang: str | None = None) -> Response:
    status, code, message = map_exception(exc)
    return err(code=code, message=message, status=status, lang=lang)


def install_error_handlers(app) -> None:
    @app.errorhandler(Exception)
    def _on_error(e: Exception):
        return handle_exception(e)
