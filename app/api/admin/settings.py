from __future__ import annotations

from typing import Any, Dict, Optional

from flask import Blueprint, request

from app.middleware.auth import apply_rate_limit, require_admin, csrf_protect, current_user
from app.services import admin_service

bp = Blueprint("admin_settings", __name__)


def _http_for(code: str) -> int:
    return {
        "ERR_INTERNAL_PAYLOAD": 400,
        "ERR_UNAUTHORIZED": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_CONFLICT": 409,
        "ERR_RATE_LIMIT": 429,
        "ERR_INTERNAL": 500
    }.get(code or "", 400)
    

def _ok(data: Any, status: int = 200):
    return ({"ok": True, "data": data}, status)


def _err(code: str, message: str):
    return ({"ok": False, "error": {"code": code, "message": message}}, _http_for(code))


def _as_envelope(res: Any) -> Dict[str, Any]:
    if isinstance(res, dict) and "ok" in res:
        return res
    return {"ok": True, "data": res or {}}


def _validate_update(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return "payload must be object"
    # Shallow shape check; deep validation is delegated to service layer.
    allowed_top = {
        "studio",
        "i18n",
        "alerts",
        "bank",
        "policies",
        "availability_presets"
    }
    for k in payload.keys():
        if k not in allowed_top:
            return f"unknown field: {k}"
    if "i18n" in payload:
        i18n = payload["i18n"]
        if not isinstance(i18n, dict):
            return "i18n must be object"
        dl = i18n.get("default_lang")
        if dl is not None and dl not in {"ko", "en"}:
            return "i18n.default_lang must be 'ko' or 'en'"
    if "availability_presets" in payload:
        ap = payload["availability_presets"]
        if not isinstance(ap, dict):
            return "availability_presets must be object"
        bd = ap.get("base_days")
        if bd is not None:
            if not isinstance(bd, list) or not all(isinstance(x, int) and 0 <= x <= 6 for x in bd):
                return "availability_presets.base_days must be int[0..6]"
    return None


@bp.get("/")
@apply_rate_limit
@require_admin
def get_settings_admin():
    try:
        res = admin_service.get_settings()  # expected to return dict or envelope
        env = _as_envelope(res)
        if env.get("ok"):
            return _ok(env.get("data") or {})
        err = (env.get("error") or {})
        return _err(err.get("code") or "ERR_INTERNAL", err.get("message") or "internal error")
    except Exception as e:
        return _err("ERR_INTERNAL", str(e))
    

@bp.get("/")
@apply_rate_limit
@require_admin
@csrf_protect
def put_settings_admin():
    try:
        body = request.get_json(silent=True)
        msg = _validate_update(body)
        if msg:
            return _err("ERR_INVALID_PAYLOAD", msg)
        
        actor = current_user() or {"id": "-", "role": "admin"}
        # Pass-through to service; it should handle merge/idempotency/audit logging.
        res = admin_service.update_settings(body or {}, actor=actor)
        env = _as_envelope(res)
        if env.get("ok"):
            return _ok(env.get("data") or {})
        err = (env.get("error") or {})
        return _err(err.get("code") or "ERR_INTERNAL", err.get("message") or "internal error")
    except Exception as e:
        return _err("ERR_INTERNAL", str(e))