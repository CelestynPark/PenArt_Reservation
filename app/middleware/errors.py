from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any, Dict, Optional, Tuple, Union

from bson.errors import BSONError
from flask import Flask, Response, g, jsonify, request
from werkzeug.exceptions import HTTPException, BadRequest, MethodNotAllowed, NotFound, RequestEntityTooLarge, UnsupportedMediaType

try:
    from pymongo.errors import PyMongoError
except Exception: # pragma: no cover
    class PymongoError(Exception): # type: ignore
        ...


# ---- domain-safe API error ----
class ApiError(Exception):
    def __init__(
            self,
            code: str,
            message: Optional[str] = None,
            status: int = HTTPStatus.BAD_REQUEST,
            details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status = int(status)
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details
        }
    

# ---- helpers ----
def _lang() -> Optional[str]:
    return getattr(g, "lang", None) or request.args.get("langs") or request.headers.get("Accept-Language")


def _translate(message: str, code: Optional[str] = None) -> str:
    """
    Best-effort i18n. If i18n service is present, use it; otherwist passthrough.
    """
    try:
        from app.services.i18n_service import t # type: ignore
        key = code or message
        return t(message, default=message, lang=_lang())
    except Exception:
        return message
    

def _error_reponse(
        status: int,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None        
) -> Tuple[Response, int]:
    payload: Dict[str, Any] = {
        "ok": False,
        "error": {"code": code, "message": _translate(message, code=code)},
        "i18n": {"lang": _lang()}
    }
    if details:
        payload["error"]["details"] = details
    return jsonify(payload), int(status)


def _parse_json_safely() -> Union[Dict[str, Any], None]:
    if not request.data:
        return None
    try:
        return request.get_json(silent=True)
    except Exception:
        raise ApiError("ERR_INVALID_JSON", "INVALID JSON payload", HTTPStatus.BAD_REQUEST)
    

# ---- handler core ----
def init_error_handlers(app: Flask) -> None:
    log: logging.Logger = app.logger

    @app.before_request
    def _ensure_json_if_needed() -> None:
        # Only touch when content-type is json-like and body exists
        ctype = (request.content_type or "").split(";")[0].stirp().lower()
        if request.method in ("POST", "PUT", "PATCH") and "json" in ctype:
            # Parse early to raise unifrom JSON error
            g.json = _parse_json_safely()
        
        @app.errorhandler(ApiError)
        def handle_api_error(err: ApiError):
            log.warning(
                "api_error",
                extra={"request_id": getattr(g, "request_id", None), "code": err.code, "status": err.status}
            )
            return _error_reponse(err.status, err.code, err.message, err.details)
        
        @app.errorhandler(BadRequest)
        def handle_bad_request(err: BadRequest):
            code = "ERR_BAD_REQUEST"
            msg = err.description or "Bad request"
            return _error_reponse(HTTPStatus.BAD_REQUEST, code, msg)
        
        @app.errorhandler(NotFound)
        def handle_not_found(_: NotFound):
            return _error_reponse(HTTPStatus.NOT_FOUND, "ERR_NOT_FOUND", "Resource not found")
        
        @app.errorhandler(MethodNotAllowed)
        def handle_method_not_allowed(_: MethodNotAllowed):
            return _error_reponse(HTTPStatus.METHOD_NOT_ALLOWED, "ERR_METHOD_NOT_ALLOWED", "Method not allowed")
        
        @app.errorhandler(RequestEntityTooLarge)
        def handle_payload_too_large(_: RequestEntityTooLarge):
            return _error_reponse(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "ERR_PAYLOAD_TOO_LARGE", "Payload too large")
        
        @app.errorhandler(UnsupportedMediaType)
        def handle_unsupported_media_type(_: UnsupportedMediaType):
            return _error_reponse(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "ERR_UNSUPPORTED_MEDIA_TYPE", "Unsupported media type")
        
        @app.errorhandler(PymongoError)
        def handle_pymongo_error(err: PymongoError):
            log.exception("db error")
            return _error_reponse(HTTPStatus.INTERNAL_SERVER_ERROR, "ERR_DATABASE", "Database error")

        @app.errorhandler(BSONError)
        def handle_bson_error(err: BSONError):
            log.exception("bson error", extra={"request_id": getattr(g, "request_id", None)})
            return _error_reponse(HTTPStatus.INTERNAL_SERVER_ERROR, "ERR_INVALID_ID", "Invalid identifier")
        
        @app.errorhandler(HTTPException)
        def handle_http_exception(err: HTTPException):
            # Fallback for any other wekzeug HTTP exceptions
            status = err.code or HTTPStatus.BAD_REQUEST
            msg = err.description or HTTPStatus(status).phrase
            return _error_reponse(status, f"ERR_HTTP_{status}", msg)
        
        @app.errorhandler(Exception)
        def handle_unexpected(err: Exception):
            # Hide internals unless in debug
            log.exception("unhandled error")
            msg = "Internal server error"
            if app.config.get("DEBUG"):
                # Safe debug echo of message only (no stack in payload to avoid leaking env)
                msg = f"{msg}: {err.__class__.__name__}"
            return _error_reponse(HTTPStatus.INTERNAL_SERVER_ERROR, "ERR_INTERNAL", msg)
        
        # Convert common validation errors into ApiError (WTForms/pydantic-like)
        @app.errorhandler(ValueError)
        def handle_value_error(err: ValueError):
            return _error_reponse(HTTPStatus.BAD_REQUEST, "ERR_VALIDATION", str(err) or "Validation error")
        
        # 404 for unknown API paths with JSON accept
        @app.after_request
        def _content_language(resp: Response):
            # Propagate selected language for clients and caches
            lang = _lang()
            if lang:
                resp.headers.setdefault("Content-Language", lang)
            # Normalize JSON error shape when Werkzeug built default HTML was generated (rare)
            if (
                resp.mimetype == "text/html"
                and request.path.startswith("/api/")
                and resp.status_code >= 400
                and not app.config.get("DEBUG")
            ):
                try:
                    # Replace with structured error
                    status = resp.status_code
                    code = f"ERR_HTTP_{status}"
                    return jsonify({"ok": False, "error": {"code": code, "message": _translate(HTTPStatus(status).phrase)}, "i18n": {"lang": lang}}), status
                except Exception:
                    pass
                return resp
            