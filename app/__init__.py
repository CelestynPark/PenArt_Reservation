from __future__ import annotations

import logging

from flask import Flask, jsonify, request, Response

from app.config import load_config
from app.extensions import init_extensions, get_mongo
from app.utils.responses import ok as ok_envelope, err as err_envelope

LOG = logging.getLogger(__name__)


def _apply_security(app: Flask) -> None:
    cfg = load_config()
    app.secret_key = cfg.secret_key
    app.config.update(
        JSON_AS_ASCII=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PREFERRED_URL_SCHEME="https",
    )

    @app.after_request
    def _security_headers(resp: Response) -> Response:
        # CSP
        if cfg.csp_enable:
            resp.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "img-src 'self' data: blob:; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "connect-src 'self'",
            )
        # Common security headers
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        return resp


def _apply_cors(app: Flask) -> None:
    cfg = load_config()
    allowed: set[str] = set(cfg.get_allowed_origins())

    @app.after_request
    def _cors_headers(resp: Response) -> Response:
        origin = request.headers.get("Origin", "")
        if origin and origin in allowed:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, X-Requested-With, X-CSRF-Token, Authorization"
            )
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            resp.headers["Access-Control-Max-Age"] = "600"
        return resp

    @app.route("/__cors__", methods=["OPTIONS"])
    def __cors_preflight__() -> Response:
        # utility route to satisfy strict preflights if needed
        return jsonify(ok_envelope())


def register_blueprints(app: Flask) -> None:
    # Placeholders; real blueprints are registered by later modules in the sequence.
    # from app.api import api_bp
    # app.register_blueprint(api_bp, url_prefix="/api")
    pass


def _register_health(app: Flask) -> None:
    @app.get("/healthz")
    def healthz() -> Response:
        return jsonify(ok_envelope())

    @app.get("/readyz")
    def readyz() -> Response:
        try:
            get_mongo().admin.command("ping")
            return jsonify(ok_envelope())
        except Exception as e:  # pragma: no cover - defensive
            LOG.exception("readyz failed: %s", e)
            resp = jsonify(err_envelope("ERR_INTERNAL", "dependency not ready"))
            return resp, 503


def create_app() -> Flask:
    app = Flask(__name__, static_folder="../static", template_folder="templates")

    # Load config and attach core protections
    load_config()  # ensure env is validated early
    _apply_security(app)
    _apply_cors(app)

    # Initialize external resources (Mongo, Scheduler)
    init_extensions(app)

    # Register routes/blueprints
    _register_health(app)
    register_blueprints(app)

    # JSONify should not escape non-ASCII
    app.json.ensure_ascii = False  # Flask 3.x JSON provider

    @app.errorhandler(404)
    def _not_found(_e) -> Response:
        return jsonify(err_envelope("ERR_NOT_FOUND", "not found")), 404

    @app.errorhandler(429)
    def _rate_limited(_e) -> Response:
        return jsonify(err_envelope("ERR_RATE_LIMIT", "too many requests")), 429

    @app.errorhandler(400)
    def _bad_request(_e) -> Response:
        return jsonify(err_envelope("ERR_INVALID_PAYLOAD", "bad request")), 400

    @app.errorhandler(500)
    def _server_error(_e) -> Response:
        return jsonify(err_envelope("ERR_INTERNAL", "internal server error")), 500

    return app
