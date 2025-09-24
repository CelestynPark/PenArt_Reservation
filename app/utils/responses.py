from __future__ import annotations

from typing import Any, Dict, Optional

__all__ = ["ERROR_CODES", "ok", "err"]

ERROR_CODES = {
    "ERR_INVALID_PAYLOAD",
    "ERR_NOT_FOUND",
    "ERR_UNAUTHORIZED",
    "ERR_FORBIDDEN",
    "ERR_CONFLICT",
    "ERR_POLICY_CUTOFF",
    "ERR_RATE_LIMIT",
    "ERR_SLOT_BLOCKED",
    "ERR_INTERNAL",
}


def ok(data: Any | None = None, i18n: dict | None = None) -> Dict[str, Any]:
    resp: Dict[str, Any] = {"ok": True}
    if data is not None:
        resp["data"] = data
    if i18n:
        resp["i18n"] = i18n
    return resp


def err(code: str, message: str, i18n: dict | None = None) -> Dict[str, Any]:
    code_norm = (code or "").strip().upper()
    if code_norm not in ERROR_CODES:
        raise ValueError(f"Invalid error code: {code}")
    resp: Dict[str, Any] = {
        "ok": False,
        "error": {"code": code_norm, "message": message},
    }
    if i18n:
        resp["i18n"] = i18n
    return resp
