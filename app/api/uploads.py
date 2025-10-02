from __future__ import annotations

from typing import Any, Dict

from flask import Blueprint, jsonify, request

from app.services import upload_service as up
from app.utils.responses import ok, err

bp = Blueprint("uploads", __name__, url_prefix="/api/uploads")


def _handle_upload(category: str):
    try:
        if "file" not in request.files:
            return jsonify(err("ERR_INVALID_PAYLOAD", "file field is required")), 400
        
        f = request.files["file"]
        filename = getattr(f, "filename", "") or ""
        mime = getattr(f, "mimetype", "") or ""

        # Validate basic inputs
        v = up.validate(f, filename, mime)
        if not v.get("ok"):
            e = v.get("error", {})
            code = e.get("code") or "ERR_INVALID_PAYLOAD"
            msg = e.get("message") or "invalid file"
            status = 403 if code in {"ERR_FORBIDDEN"} else 400
            return jsonify(err(code, msg)), status
        
        # Store (streaming, AV scan, path guards inside service)
        res = up.store(f, filename, category=category, mime=mime)
        if not res.get("ok"):
            e = res.get("error", {})
            code = e.get("code") or "ERR_INTERNAL"
            msg = e.get("message") or "upload failed"
            status = 500 if code == "ERR_INTERNAL" else 403 if code == "ERR_FORBIDDEN" else 400
            return jsonify(err(code, msg)), status
        
        data = res.get("data", {})
        payload: Dict[str, Any] = {
            "url": data.get("url"),
            "size": data.get("size"),
            "mime": data.get("mime")
        }
        return jsonify(ok(payload))
    except Exception:
        return jsonify(err("ERR_INTERNAL", "internal error")), 500
    

@bp.post("/reviews")
def upload_review_image():
    return _handle_upload("reviews")


@bp.post("/receipts")
def upload_receipt_image():
    return _handle_upload("receipts")

