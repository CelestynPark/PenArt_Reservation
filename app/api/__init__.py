from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import Blueprint, Flask, Response, jsonify, request

from app.core.constants import API_DATA_KEY, API_ERROR_KEY, API_OK_KEY
from app.middleware.errors import register_error_handlers
from app.middleware.i18n import i18n_after_request, i18n_before_request
from app.utils.rate_limit import RateLimitError, check_rate_limit, rate_limit_key, remaining

API_PREFIX = "/api"


def _client_ip() -> str:
    """
    X-Forwarded-For가 있으면 첫 번째 IP를 사용하고, 없으면 request.remote_addr를 사용한다.
    """
    fwd = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return fwd or (request.remote_addr or "-")


def _rate_limit_before_request() -> Optional[Response]:
    """
    요청 전 레이트 리밋 체크. 초과 시 429 JSON 에러를 반환한다.
    """
    try:
        key= rate_limit_key(_client_ip(), None)
        check_rate_limit(key)
    except RateLimitError as e:
        resp = jsonify({API_OK_KEY: False, API_ERROR_KEY: {"code": "ERR_RATE_LIMIT", "message": str(e)}})
        resp.status_code = 429
        return resp
    return None


def _rate_limit_after_request(resp: Response) -> Response:
    """
    응답 후 남은 쿼터를 헤더를 내려준다. (오류는 조용히 무시)
    """
    try:
        key = rate_limit_key(_client_ip(), None)
        rem = remaining(key)
        resp.headers["X-RateLimit-Remaining"] = str(rem)
    except Exception:
        pass
    return resp


def create_api_blueprint() -> Blueprint:
    """
    /api 루트 블루프린트 생성 및 하위 블루프린트 등록.
    """
    bp = Blueprint("api", __name__)

    @bp.before_request
    def _i18n_and_rl_before() -> Optional[Response]:
        i18n_before_request()
        return _rate_limit_before_request()
    
    @bp.after_request
    def _i18n_and_rl_after(resp: Response) -> Response:
        resp = _rate_limit_after_request(resp)
        resp = i18n_after_request(resp)
        return resp
    
    # sub-blueprints (lazy import to avoid cycles)
    from app.api.auth import bp as auth_bp  # noqa: WPS433
    from app.api.me import bp as me_bp  # noqa: WPS433

    bp.register_blueprint(auth_bp, url_prefix="/auth")
    bp.register_blueprint(me_bp, url_prefix="/me")

    @bp.get("/")
    def ping() -> Tuple[Dict[str, Any], int]:
        return {API_OK_KEY: True, API_DATA_KEY: {"service": "api"}}, 200
    
    return bp


def register_api(app: Flask) -> None:
    """
    에러 핸드러 등록 후 /api 블루프린트 앱에 장착한다.
    """
    register_error_handlers(app)
    app.register_blueprint(create_api_blueprint(), url_prefix=API_PREFIX)

    