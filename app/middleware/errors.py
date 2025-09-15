from __future__ import annotations

import logging
import uuid
from typing import Any, Tuple

from flask import Flask, request, g
from werkzeug.exceptions import (
    HTTPException,
    BadRequest,
    Unauthorized,
    Forbidden,
    NotFound,
    MethodNotAllowed,
    Conflict,
    UnsupportedMediaType,
    RequestEntityTooLarge,
    TooManyRequests,
)

from app.core.constants import ErrorCode
from app.utils.responses import fail

logger = logging.getLogger(__name__)


def _ensure_request_id() -> str:
    rid = getattr(g, "request_id", None) or request.headers.get("X-Request-ID")
    if not rid:
        rid = uuid.uuid4().hex
    g.request_id = rid
    return rid


def _request_ctx() -> dict:
    return {
        "request_id": _ensure_request_id(),
        "method": request.method,
        "path": request.full_path if request.query_string else request.path,
        "ip": request.headers.get("X-Forwarded-For", request.remote_addr),
        "ua": request.user_agent.string if request.user_agent else "",
    }


def _extract_custom_error(e: Exception) -> Tuple[str, int, str]:
    code = getattr(e, "code", None)
    if isinstance(code, ErrorCode):
        return code.value, 400, str(e)
    if isinstance(getattr(e, "error_code", None), ErrorCode):
        return e.error_code.value, 400, str(e)
    return ErrorCode.INTERNAL.value, 500, "Internal server error"


def _log(level: int, status: int, e: Exception, msg: str) -> None:
    data = _request_ctx() | {"status": status, "message": msg, "etype": type(e).__name__}
    logger.log(level, "error_response", extra={"context": data}, exc_info=status >= 500)


def _handle_http_exception(e: HTTPException):
    mapping: dict[type, tuple[str, int]] = {
        BadRequest: (ErrorCode.INVALID_PAYLOAD.value, 400),
        Unauthorized: (ErrorCode.UNAUTHORIZED.value, 401),
        Forbidden: (ErrorCode.FORBIDDEN.value, 403),
        NotFound: (ErrorCode.NOT_FOUND.value, 404),
        MethodNotAllowed: (ErrorCode.INVALID_PAYLOAD.value, 405),
        Conflict: (ErrorCode.CONFLICT.value, 409),
        RequestEntityTooLarge: (ErrorCode.INVALID_PAYLOAD.value, 413),
        UnsupportedMediaType: (ErrorCode.INVALID_PAYLOAD.value, 415),
        TooManyRequests: (ErrorCode.RATE_LIMIT.value, 429),
    }
    code, status = mapping.get(type(e), (ErrorCode.INTERNAL.value, 500))
    message = getattr(e, "description", "") or e.name or "Error"
    _log(logging.WARNING if status < 500 else logging.ERROR, status, e, message)
    return fail(code=code, message=message, status=status)


def _handle_key_error(e: KeyError):
    field = str(e).strip("'\"")
    message = f"Missing field: {field}" if field else "Invalid payload"
    _log(logging.WARNING, 400, e, message)
    return fail(code=ErrorCode.INVALID_PAYLOAD, message=message, status=400)


def _handle_value_error(e: ValueError):
    message = str(e) or "Invalid payload"
    _log(logging.WARNING, 400, e, message)
    return fail(code=ErrorCode.INVALID_PAYLOAD, message=message, status=400)


def _handle_type_error(e: TypeError):
    message = str(e) or "Invalid payload"
    _log(logging.WARNING, 400, e, message)
    return fail(code=ErrorCode.INVALID_PAYLOAD, message=message, status=400)


def _handle_permission_error(e: PermissionError):
    message = str(e) or "Forbidden"
    _log(logging.WARNING, 403, e, message)
    return fail(code=ErrorCode.FORBIDDEN, message=message, status=403)


def _handle_custom_or_internal(e: Exception):
    code, status, message = _extract_custom_error(e)
    if status >= 500 and code == ErrorCode.INTERNAL.value:
        message = "Internal server error"
    _log(logging.WARNING if status < 500 else logging.ERROR, status, e, message)
    return fail(code=code, message=message, status=status)


def register_error_handlers(app: Flask) -> None:
    app.register_error_handler(HTTPException, _handle_http_exception)
    app.register_error_handler(KeyError, _handle_key_error)
    app.register_error_handler(ValueError, _handle_value_error)
    app.register_error_handler(TypeError, _handle_type_error)
    app.register_error_handler(PermissionError, _handle_permission_error)
    app.register_error_handler(Exception, _handle_custom_or_internal)
