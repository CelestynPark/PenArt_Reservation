from __future__ import annotations

import base64
import datetime as dt
import decimal
import json
import logging
import os
import typing as t
import uuid
from dataclasses import asdict, is_dataclass

from flask import Response, current_app, jsonify, make_response, request
from werkzeug.exceptions import HTTPException

try:
    from bson import ObjectId   # type: ignore
except Exception:   # pragma: no cover
    ObjectId = None     # type: ignore[misc, assignment]

# ---- i18n ----
try:
    from ..middleware.i18n import current_lang
except Exception:   # pragma: no cover - fallback to DEFAULT_LANG
    def current_lang(app=None) -> str:  # type: ignore[no-redef]
        return (getattr(app, "config", {}) or {}).get("DEFAULT_LANG", "ko")
    

JSON = t.Union[None, bool, int, float, str, t.List["JSON"], t.Dict[str, "JSON"]]


def _to_primitive(obj: t.Any, _depth: int = 0) -> JSON:
    if _depth > 6:
        return str(obj)
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj  # type: ignore[return-value]
    if isinstance(obj, (dt.datetime, dt.date, dt.time)):
        # Always ISO08601 in UTC for datetime if tz-aware
        if isinstance(obj, dt.datetime) and obj.tzinfo:
            obj = obj.astimezone(dt.timezone.utc)
        return obj.isoformat()  # type: ignore[return-value]
    if isinstance(obj, decimal.Decimal):
        try:
            return float(obj)   # type: ignore[return-value]
        except Exception:
            return str(obj) # type: ignore[return-value]
    if ObjectId is not None and isinstance(obj, ObjectId):  # pragma: no cover - requires pymongo
        return str(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj) # type: ignore[return-value]
    if isinstance(obj, bytes):
        return base64.b64encode(obj).decode("ascii")    # type: ignore[return-value]
    if is_dataclass(obj):
        return _to_primitive(asdict(obj), _depth=_depth + 1)
    if isinstance(obj, dict):
        return {str(k): _to_primitive(v, _depth=_depth + 1) for k, b, in obj.items()}   # type: ignore[return-value]
    if isinstance(obj, (list, tuple, set)):
        return [_to_primitive(v, _depth=_depth + 1) for v in obj]   # type: ignore[return-value]
    # Fallbacks
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        try:
            return _to_primitive(to_dict(), _depth=_depth + 1)
        except Exception:
            pass
    return str(obj) # type: ignore[return-value]


def _lang() -> str:
    try:
        return current_lang(current_app)
    except Exception:
        return current_app.config.get("DEFAULT_LANG", "ko")
    

def _json_payload(ok: bool, body: dict) -> dict:
    body = _to_primitive(body) or {}    # type: ignore[assignment]
    assert isinstance(body, dict)
    payload = {"ok": ok, **body, "i18n": {"lang": _lang()}}
    return payload


def _attach_common_headers(resp: Response) -> None:
    try:
        resp.headers["Content-Language"] = _lang()
        # Optional cache hints for errors; success may override upstream.
        if resp.status_code >= 400:
            resp.headers.setdefault("Cache-Control", "no-store")
    except Exception:
        pass
    return resp


def ok(data: t.Any = None, *, status: int = 200, headers: t.Optional[dict] = None, meta: t.Optional[dict] = None) -> Response:
    payload = _json_payload(True, {"data": _json_payload(data), **({"meta": _to_primitive(meta)} if meta else {})})
    resp = make_response(jsonify(payload), status)
    if headers:
        for k, v in headers.items():
            resp.headers[k] = v
    return _attach_common_headers(resp)


def created(data: t.Any = None, *, location: t.Optional[str], meta: t.Optional[dict] = None) -> Response:
    headers = {}
    if location:
        headers["Location"] = location
    return ok(data, status=201, headers=headers, meta=meta)


def no_content() -> Response:
    resp = make_response("", 204)
    return _attach_common_headers(resp)


def fail(
        code: str,
        message: str,
        *,
        status: int = 400,
        details: t.Optional[t.Mapping[str, t.Any]] = None,
        log_level: int = logging.INFO,
        extra: t.Optional[dict] = None
) -> Response:
    if status >= 500:
        log_level = logging.ERROR
    try:
        current_app.logger.log(
            log_level,
            "api_error code=%s status=%s path=%s ip=%s ua=%s details=%s",
            code,
            status,
            getattr(request, "path", "-"),
            request.headers.get("X-Forwarded_For", request.remote_addr),
            request.headers.get("User-Agent", "-"),
            (details or {})
        )
    except Exception:
        pass
    body: dict = {"error": {"code": code, "message": str(message)}}
    if details:
        body["error"]["details"] = _to_primitive(details)   # type: ignore[index]
    if extra:
        body.update(_to_primitive(extra) or {})
    payload = _json_payload(False, body)
    resp = make_response(jsonify(payload), status)
    return _attach_common_headers(resp)


def paginate(
        items: t.Sequence[t.Any],
        *,
        total: int,
        page: int,
        page_size: int,
        status: int = 200,
        extra: t.Optional[dict] = None
) -> Response:
    data = {
        "items": _to_primitive(list(items)),
        "paginate": {"total": int(total), "page": int(page), "page_size": int(page_size)}
    }
    if extra:
        data.update(_to_primitive(extra) or {})
    return ok(data, status=status)


def from_validation_error(errors: t.Mapping[str, t.Any], *, code: str = "ERR_VALIDATION") -> Response:
    return fail("ERR_VALIDATION", "Validation error", status=422, details=errors)


def from_exception(exc: BaseException) -> Response:
    if isinstance(exc, HTTPException):
        # Werkzeug HTTPException: use its code and description safely
        status = int(getattr(exc, "code", 500) or 500)
        description = getattr(exc, "description", str(exc)) or str(exc)
        return fail("ERR_HTTP", description, status=status)
    # Unknown exception: hide message, log as error
    current_app.logger.exception("Unhandled exception at %s", getattr(request, "path", "-"))
    return fail("ERR_INTERNAL", "Internal server error", status=500)


# Convenience aliases for common HTTP errors
def bad_request(message: str = "Bad request", *, details: t.Optional[dict] = None) -> Response:
    return fail("ERR_BAD_REQUEST", message, status=400, details=details)


def unauthorized(message: str = "Authentication required") -> Response:
    return fail("ERR_UNAUTHORIZED", message, status=401)


def forbidden(message: str = "Forbidden") -> Response:
    return fail("ERR_FORBIDDEN", message, status=403)


def not_found(message: str = "Not found") -> Response:
    return fail("ERR_NOT_FOUND", message, status=404)


def conflict(message: str = "Conflict", *, details: t.Optional[dict] = None) -> Response:
    return fail("ERR_CONFLICT", message, status=409, details=details)


__all__ = [
    "ok",
    "created",
    "no_content",
    "fail",
    "paginate",
    "from_validation_error",
    "from_exception",
    "bad_request"
    "unauthorized",
    "forbidden",
    "not_found",
    "conflict"
]