from __future__ import annotations
import logging
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from .config import Config
from .db import ensure_indexes, get_db


def create_app(config_object: type[Config] | None = None) -> Flask:
    """
    Flask Application Factory:
    - 설정 로딩
    - CORS & 보안 해더
    - 전역 오류 핸들러(JSON)
    - 기본 인덱스 보증
    """
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(config_object or Config)

    # 로깅(간단)
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

    # CORS: 필요 시만 허용
    cors_origins = app.config.get("CORS_ALLOW_ORIGINS") or []
    if cors_origins:
        CORS(app, resources={r"/api/*": {"origins": cors_origins}}, supports_credentials=True)
    
    @app.after_request
    def security_headers(resp):
        # 기본 보안 해더(필요 시 CSP 강화)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame_Options", "SAMEORIGIN")
        resp.headers.setdefault("X-XSS-Protection", "0")
        # 간단한 CSP (탬플릿/정적자원 기준. 필요 시 수정)
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'",
        )
        return resp
    
    # 전역 에러 핸들러: JSON 표준화
    @app.errorhandler(Exception)
    def handle_exceptions(e: Exception):
        if isinstance(e, HTTPException):
            code = e.code or 500
            return jsonify({"ok": False, "error": e.name, "messsage": getattr(e, "description", str(e))}), code
        app.logger.exception("Unhandled Exception")
        return jsonify({"ok": False, "error": "InternalServerError", "message": "서버 내부 오류"}), 500

    # 헬스체크 & DB 핑
    @app.get("/api/health")
    def health():
        try:
            db = get_db()
            #  간단한 ping
            db.list_collection_names()
            return jsonify({"ok": True, "message": "healthy"}), 200
        except Exception as e:
            app.logger.error("Health check failed")
            return jsonify({"ok": False, "error": "DB", "message": str(e)}), 500
        
        # === 여기서부터 블루프린트 등록 ===

        from .views import bp as views_bp
        app.register_blueprint(views_bp)

        # 인덱스 보증(앱 기동 시 1회)
        with app.app_context():
            ensure_indexes()

        return app
    