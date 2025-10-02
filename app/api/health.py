from __future__ import annotations

from flask import Blueprint, jsonify, current_app
from pymongo.errors import PyMongoError

from app.utils.responses import ok, err
from app.core.constants import ErrorCode
from app.extensions import get_mongo

bp = Blueprint("health", __name__)

READYZ_TIMEOUT_MS = 500


@bp.get("/healthz")
def healthz():
    return jsonify(ok({"status": "ok"}))


@bp.get("/readyz")
def readyz():
    mongo_status = "fail"
    tmpl_status = "fail"

    # Mongo ping
    try:
        client = get_mongo()
        client.admin.command("ping", maxTimeMs=READYZ_TIMEOUT_MS)
        mongo_status = "ok"
    except (PyMongoError, Exception):
        mongo_status = "fail"
    
    # Templates engine smoke
    try:
        env = getattr(current_app, "jinja_env", None)
        if env is not None:
            env.from_string("ok").render()
            tmpl_status = "ok"
        else:
            tmpl_status = "fail"
    except Exception:
        tmpl_status = "fail"

    data = {"mongo": mongo_status, "templates": tmpl_status}
    if mongo_status == "ok" and tmpl_status == "ok":
        return jsonify(ok(data))
    resp = err(ErrorCode.ERR_INTERNAL.value, "dependencies not ready")
    resp["data"] = data
    return jsonify(resp), 503