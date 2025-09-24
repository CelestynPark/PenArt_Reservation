from __future__ import annotations

import json
from typing import Any, Optional, Mapping

from flask import Response, g
from app.core.constants import LANG_KO, ErrorCode

__all__ = ["ok", "fail"]


def _json_response(payload: Mapping[str, Any], status: int) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        status=status,
        mimetype="application/json; charset=utf-8",
    )


def _resolve_lang(i18n: Optional[dict] = None) -> Optional[dict]:
    if i18n and isinstance(i18n, dict) and i18n.get("lang"):
        return {"lang": str(i18n["lang"])}
    lang = getattr(g, "lang", None)
    return {"lang": lang or LANG_KO} if lang or i18n is not None else None


def _err_code(code: Any) -> str:
    if isinstance(code, ErrorCode):
        return code.value
    return str(code or ErrorCode.INTERNAL.value)


def ok(data: Any = None, i18n: Optional[dict] = None, status: int = 200) -> Response:
    if status >= 400:
        status = 200
    payload: dict[str, Any] = {"ok": True}
    if data is not None:
        payload["data"] = data
    lang = _resolve_lang(i18n)
    if lang:
        payload["i18n"] = lang
    return _json_response(payload, status)


def fail(
    code: Any,
    message: str,
    status: int = 400,
    i18n: Optional[dict] = None,
) -> Response:
    if status < 400:
        status = 400
    payload: dict[str, Any] = {
        "ok": False,
        "error": {"code": _err_code(code), "message": str(message)},
    }
    lang = _resolve_lang(i18n)
    if lang:
        payload["i18n"] = lang
    return _json_response(payload, status)
