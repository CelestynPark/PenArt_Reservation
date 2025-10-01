from __future__ import annotations

from typing import Any, Dict, Tuple

from flask import Blueprint, Response, jsonify, make_response, request

from app.core.constants import API_DATA_KEY, API_ERROR_KEY, API_OK_KEY
from app.middleware.auth import apply_rate_limit, csrf_protect, require_login
from app.services import auth_service
from app.utils.security import COOKIE_NAME as CSRF_COOKIE_NAME, generate_csrf

bp = Blueprint("auth", __name__)


def _status_for(code: str) -> int:
    return {
        "ERR_INVALID_PAYLOAD": 400,
        "ERR_UNAUTHORIZED": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_CONFLICT": 409,
        "ERR_POLICY_CUTOFF": 409,
        "ERR_RATE_LIMIT": 429,
        "ERR_SLOT_BLOCKED": 409,
        "ERR_INTERNAL": 500
    }.get(code or "", 400)


@bp.post("/magiclink")
@apply_rate_limit
def post_magiclink() -> Tuple[Dict[str, Any], int]:
    """
    이메일을 입력받아 매직링크를 발급한다.
    성공 시 토큰을 절대 응답하지 않는다.
    """
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()
    res = auth_service.issue_magiclink(email)
    if res.get(API_OK_KEY):
        # Do not leak token
        return {API_OK_KEY: True}, 200
    
    err = (res.get(API_ERROR_KEY) or {})
    return {API_OK_KEY: False, API_ERROR_KEY: err}, _status_for(err.get("code"))


@bp.post("/verify")
@apply_rate_limit
def post_verify() -> Response:
    """
    매직링크 토큰 검증 -> 세션 쿠키/헬퍼 쿠키/CSRF 쿠키 설정.
    """
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or "").strip()

    ua = request.headers.get("User-Agent") or ""
    ip = (request.headers.get("X-Forwarded-For", "") or "").split(",")[0].strip() or (request.remote_addr or "")

    res = auth_service.verify_token(token, ua=ua, ip=ip)
    if not res.get(API_OK_KEY):
        err = (res.get(API_ERROR_KEY) or {})
        resp = jsonify({API_OK_KEY: False, API_ERROR_KEY: err})
        resp.status_code = _status_for(err.get("code"))
        return resp
    
    data = (res.get(API_DATA_KEY) or {})
    sess = (res.get("session") or {})
    session_id = (sess.get("session_id") or "").strip()
    uid = (sess.get("user_id") or "").strip()
    role = (sess.get("role") or "customer").strip() or "customer"

    # 본문에는 민감 정보 미포함
    resp = make_response(jsonify({API_OK_KEY: True, API_DATA_KEY: {"session": {"user_id": uid, "role": role}}}))

    # Session cookie (HttpOnly)
    resp.set_cookie("session_id", session_id, httponly=True, secure=True, samesite="Lax", path="/")

    # Light helpers for dev/tests (비-HttpOnly)
    resp.set_cookie("uid", uid, httponly=False, secure=True, samesite="Lax", path="/")
    resp.set_cookie("role", role, httponly=False, secure=True, samesite="Lax", path="/")

    # CSRF double-submit cookie (value derived from session_id)
    csrf_token = generate_csrf(session_id)
    resp.set_cookie(CSRF_COOKIE_NAME, csrf_token, httponly=False, secure=True, samesite="Lax", path="/")

    return resp


@bp.post("/logout")
@apply_rate_limit
@require_login
@csrf_protect
def post_logout() -> Tuple[Dict[str, Any], int]:
    """
    세션 종료 및 관련 쿠키 제거.
    """
    sid = request.cookies.get("session_id") or request.headers.get("X-Session-Id") or ""
    res = auth_service.logout(sid)
    if not res.get(API_OK_KEY):
        err = (res.get(API_OK_KEY) or {})
        return {API_OK_KEY: False, API_ERROR_KEY: err}, _status_for(err.get("code"))
    
    # 쿠키 삭제
    from app.utils.security import COOKIE_NAME as CSRF_COOKIE   # 동일 상수 사용
    resp = make_response(jsonify({API_OK_KEY: True}))
    for cname in ("session_id", "uid", "role", CSRF_COOKIE):
        resp.set_cookie(cname, "", expires=0, path="/")
    return {"ok": True}, 200    # (호출 측 일관서을 위해 튜플 반환)
