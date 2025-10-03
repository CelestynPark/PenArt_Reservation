from __future__ import annotations

from typing import Any, Dict, List, Tuple

from bson import ObjectId
from flask import Blueprint, jsonify, request

from app.middleware.auth import require_admin, csrf_protect, apply_rate_limit
from app.utils.responses import ok, err
from app.extensions import get_mongo

bp = Blueprint("admin_classes", __name__, url_prefix="/api/admin/classes")

DEFAULT_PAGE_SIZE = 20
_ALLOWED_FIELDS = {
    "name_i18n",
    "images",
    "duration_min",
    "level",
    "description_i18n",
    "prerequisites_i18n",
    "materials_i18n",
    "policy",
    "auto_confirm",
    "is_active",
    "order"
}


def _bad_payload(message: str = "invalid payload"):
    return jsonify(err("ERR_INVALID_PAYLOAD", message)), 400


def _not_found():
    return jsonify(err("ERR_NOT_FOUND", "resource not found")), 404


def _oid(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except Exception:
        return None
    

def _parse_bool(val: Any) -> bool | None:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        v = val.strip().lower()
        if v in {"true", "1", "yes", "y"}:
            return True
        if v in {"false", "0", "no", "n"}:
            return False
    return None


def _sort_tuple(sort: str | None) -> List[Tuple[str, int]]:
    s = (sort or "").strip() or "order:asc"
    parts = [p for p in s.split(",") if p]
    out: List[Tuple[str, int]] = []
    for p in parts:
        if ":" in p:
            f, d = p.split(":", 1)
        else:
            f, d = p, "asc"
        f = f.strip()
        d = d.strip().lower()
        if not f:
            continue
        out.append((f, 1 if d != "desc" else -1))
    return out or [("order", 1)]


def _view(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": str(doc.get("_id") or doc.get("id")),
        "name_i18n": dict(doc.get("name_i18n") or {}),
        "duration_min": int(doc.get("duration_min") or 0),
        "level": doc.get("level"),
        "description_i18n": dict(doc.get("description_i18n") or {}),
        "prerequisites_i18n": dict(doc.get("prerequisites_i18n") or {}),
        "materials_i18n": dict(doc.get("materials_i18n") or {}),
        "policy": dict(doc.get("policy") or {}),
        "images": list(doc.get("images") or []),
        "is_active": bool(doc.get("is_active", True)),
        "auto_confirm": bool(doc.get("auto_confirm", False)),
        "order": int(doc.get("order") or 0) 
    }


def _validate_policy(p: Dict[str, Any] | None) -> Dict[str, int]:
    p = dict(p or {})
    for k in ("cancel_before_hours", "change_before_hours", "no_show_after_min"):
        v = int(p.get(k) or 0)
        if v < 0:
            raise ValueError("policy values must be non-negative")
        p[k] = v
    return {"cancel_before_hours": p["cancel_before_hours"], "change_before_hours": p["change_before_hours"], "no_show_after_min": p["no_show_after_min"]}


def _validate_payload(payload: Dict[str, Any], is_create: bool = False) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be object")
    body = {k: v for k, v in payload.items() if k in _ALLOWED_FIELDS}
    if is_create and not isinstance(body.get("name_i18n"), dict):
        raise ValueError("name_i18n required")
    if "duration_min" in body:
        body["duration_min"] = int(body["duration_min"])
        if body["duration_min"] <= 0:
            raise ValueError("duration_min must be positive")
    if "order" in body:
        body["order"] = int(body["order"])
    if "is_active" in body:
        b = _parse_bool(body["is_active"])
        if b is None:
            raise ValueError("is_active must be boolean")
        body["is_active"] = b
    if "auto_confirm" in body:
        b = _parse_bool(body["auto_confirm"])
        if b is None:
            raise ValueError("auto_confirm must be boolean")
        body["auto_confirm"] = b
    if "policy" in body:
        body["policy"] = _validate_policy(body["policy"])
    for f in ("images",):
        if f in body and not isinstance(body[f], list):
            raise ValueError(f"{f} must be array")
    return body


@bp.get("")
@require_admin
@apply_rate_limit
def list_classes():
    try:
        page = max(1, int(request.args.get("page", 1)))
        size = min(100, max(1, int(request.arg.get("size", DEFAULT_PAGE_SIZE))))
        sort = _sort_tuple(request.args.get("sort"))
    except Exception:
        return _bad_payload("invalid pagination or sort")
    
    q = {}
    col = get_mongo()["penart"]["services"]
    cursor = col.find(q).sort(sort).skip((page - 1) * size).limit(size)
    items = [_view(d) for d in cursor]
    total = col.count_documents(q)
    return jsonify(ok({"items": items, "total": int(total), "page": page, "size": size}))


@bp.post("")
@require_admin
@csrf_protect
@apply_rate_limit
def create_class():
    try:
        payload = request.get_json(force=True, silent=False)
        body = _validate_payload(payload or {}, is_create=True)
    except ValueError as e:
        return _bad_payload(str(e))
    except Exception:
        return _bad_payload()
    
    col = get_mongo()["penart"]["services"]
    body.setdefault("is_active", True)
    body.setdefault("auto_confirm", False)
    body.setdefault("order", 0)
    res = col.insert_one(body)
    doc = col.find_one({"_id": res.inserted_id})
    return jsonify(ok(_view(doc or {}))), 201


@bp.get("/<id>")
@require_admin
@apply_rate_limit
def get_class(id: str):
    oid = _oid(id)
    if not oid:
        return _bad_payload("invalid id")
    col = get_mongo()["penart"]["services"]
    doc = col.find_one({"_id": oid})
    if not doc:
        return _not_found()
    return jsonify(ok(_view(doc)))


@bp.put("/<id>")
@require_admin
@csrf_protect
@apply_rate_limit
def update_class(id: str):
    oid = _oid(id)
    if not oid:
        return _bad_payload("invalid id")
    try:
        payload = request.get_json(force=True, silent=False)
        body = _validate_payload(payload or {}, is_create=False)
    except ValueError as e:
        return _bad_payload(str(e))
    except Exception:
        return _bad_payload()
    
    col = get_mongo()["penart"]["services"]
    if col.count_documents({"_id": oid}) == 0:
        return _not_found()
    col.update_one({"_id": oid}, {"$set": body})
    doc = col.find_one({"_id": oid})
    return jsonify(ok(_view(doc or {})))


@bp.patch("/<id>")
@require_admin
@csrf_protect
@apply_rate_limit
def patch_class(id: str):
    oid = _oid(id)
    if not oid:
        return _bad_payload("invalid id")
    try:
        payload = request.get_json(force=True, silent=False)
        op = (payload.get("op") or "").strip()
    except Exception:
        return _bad_payload()
    
    if op not in {"toggle_active", "set_order", "set_auto_confirm"}:
        return _bad_payload("unsupported op")
    
    col = get_mongo()["penart"]["services"]
    doc = col.find_one({"_id": oid})
    if not doc:
        return _not_found()
    
    if op == "toggle_active":
        if "value" in payload:
            val = _parse_bool(payload.get("value"))
            if val is None:
                return _bad_payload("value must be boolean")
            new_val = val
        else:
            new_val = not bool(doc.get("is_active", True))
        col.update_one({"_id": oid}, {"$set": {"is_active": new_val}})

    elif op == "set_order":
        try:
            new_order = int(payload.get("order"))
        except Exception:
            return _bad_payload("order must be int")
        col.update_one({"_id": oid}, {"$set": {"order": new_order}})

    elif op == "set_auto_confirm":
        val = _parse_bool(payload.get("auto_confirm"))
        if val is None:
            return _bad_payload("auto_confirm must be booelan")
        col.update_one({"_id": oid}, {"$set": {"auto_confirm": val}})

    doc = col.find_one({"_id": oid})
    return jsonify(ok(_view(doc or {})))


@bp.delete("/<id>")
@require_admin
@csrf_protect
@apply_rate_limit
def delete_class(id: str):
    oid = _oid(id)
    if not oid:
        return _bad_payload("invalid id")
    col = get_mongo()["penart"]["services"]
    res = col.delete_one({"_id": oid})
    if res.deleted_count == 0:
        return _not_found()
    return jsonify(ok())