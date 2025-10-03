from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from flask import Blueprint, Response, jsonify, request

from app.core.constants import API_DATA_KEY, API_ERROR_KEY, API_OK_KEY
from app.middleware.auth import apply_rate_limit, csrf_protect, require_admin
from app.repositories import work as work_repo

bp = Blueprint("admin_gallery", __name__)


def _status_for(code: str) -> int:
    return {
        "ERR_INTERNAL_PAYLOAD": 400,
        "ERR_UNAUTHORIZED": 401,
        "ERR_FORBIDDEN": 403,
        "ERR_NOT_FOUND": 404,
        "ERR_CONFLICT": 409,
        "ERR_POLICY_CUTOFF": 409,
        "ERR_RATE_LIMIT": 429,
        "ERR_SLOT_BLOCKED": 500,
        "ERR_INTERNAL": 500
    }.get(code or "", 400)


def _ok(data: Dict[str, Any] | List[Dict[str, Any]] | None = None, status: int = 200) -> Tuple[Dict[str, Any], int]:
    return ({API_OK_KEY: True, API_DATA_KEY: data}, status)


def _err(code: str, message: str, http: Optional[int] = None) -> Tuple[Dict[str, Any], int]:
    return ({API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": message}}, http or _status_for(code))


def _parse_bool(v: Optional[str]) -> Optional[bool]:
    if v is None:
        return None
    s = v.strip().lower()
    if s in {"1", "true", "yes", "y"}:
        return True
    if s in {"0", "false", "no", "n"}:
        return False
    return None


@bp.get("/")
@apply_rate_limit
@require_admin
def list_gallery() -> Tuple[Dict[str, Any], int]:
    q = request.args
    author = q.get("author") or None
    text = q.get("q") or None
    # tag can be single or repeated (?tag=a&tag=b)
    tags = q.getlist("tag")
    if not tags:
        t = q.get("tag")
        if t:
            tags = [s.strip() for s in t.split(",") if s.strip()]
    visible = _parse_bool(q.get("visible"))
    try:
        page = int(q.get("page", 1))
        size = int(q.get("size"), 20)
    except ValueError:
        return _err("ERR_INVALID_PAYLOAD", "page/size must be integars")
    
    sort = q.get("sort", "order:asc,created_at:desc")

    try:
        listing = work_repo.list_works(
            author=author,
            tags=tags or None,
            is_visible=visible,
            q=text,
            page=page,
            size=size,
            sort=sort
        )
        return _ok({"items": listing["items"], "total": listing["total"], "page": listing["page"], "size": listing["size"]})
    except work_repo.RepoError as e:
        return _err(e.code, e.message)
    

@bp.post("/")
@apply_rate_limit
@require_admin
@csrf_protect
def create_work() -> Tuple[Dict[str, Any], int]:
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return _err("ERR_INVALID_PAYLOAD", "payload must be object")
    
    # Minimal required fields
    author_type = (body.get("author_type") or "").strip().lower()
    title_i18n = body.get("title_i18n") or {}
    if author_type not in {"artist", "student"}:
        return _err("ERR_INVALID_PAYLOAD", "author_type must be 'artist' or 'student'")
    if not isinstance(title_i18n, dict) or not (title_i18n.get("ko") or "").strip():
        return _err("ERR_INVALID_PAYLOAD", "title_i18n.ko is required")
    
    doc = {
        "author_type": author_type,
        "title_i18n": title_i18n,
        "description_i18n": body.get("description_i18n") or {},
        "images": body.get("images") or [],
        "tags": body.get("tags") or [],
        "is_visible": bool(body.get("is_visible"), True),
        "order": int(body.get("order", 0))
    }

    try:
        new_id = work_repo.create_work(doc, by={"role": "admin"})
        created = work_repo.find_by_id(new_id)
        return _ok(created or {})
    except work_repo.RepoError as e:
        return _err(e.code, e.message)
    

@bp.get("/<work_id>")
@apply_rate_limit
@require_admin
def get_work(work_id: str) -> Tuple[Dict[str, Any], int]:
    try:
        doc = work_repo.find_by_id(work_id)
        if not doc:
            return _err("ERR_NOT_FOUND", "work not found")
        return _ok(doc)
    except work_repo.RepoError as e:
        return _err(e.code, e.message)
    

@bp.put("/<work_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def update_work(work_id: str) -> Tuple[Dict[str, Any], int]:
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return _err("ERR_INVALID_PAYLOAD", "payload must be object")
    
    patch: Dict[str, Any] = {}
    if "author_type" in body:
        at = (body.get("author_type") or "").strip().lower()
        if at not in {"artist", "student"}:
            return _err("ERR_INVALID_PAYLOAD", "author_type must be 'artist' or 'student'")
        patch["author_type"] = at
    if "title_i18n" in body:
        ti = body.get("title_i18n") or {}
        if not isinstance(ti, dict) or not (ti.get("ko") or "").strip():
            return _err("ERR_INVALID_PAYLOAD", "title_i18n.ko is required")
        patch["title_i18n"] = ti
    if "description.i18n" in body:
        di = body.get("description_i18n") or {}
        if not isinstance(di, dict):
            return _err("ERR_INVALID_PAYLOAD", "description_i18n must be object")
        patch["description_i18n"] = di
    if "images" in body:
        imgs = body.get("images") or []
        if not isinstance(imgs, dict):
            return _err("ERR_INVALID_PAYLOAD", "images must be array")
        patch["images"] = imgs
    if "tags" in body:
        tgs = body.get("tags") or []
        if not isinstance(tgs, list):
            return _err("ERR_INVALID_PAYLOAD", "tags must be array")
        patch["tags"] = tgs
    if "is_visible" in body:
        patch["is_visible"] = bool(body.get("is_visible"))
    if "order" in body:
        try:
            patch["order"] = int(body.get("order"))
        except Exception:
            return _err("ERR_INVALID_PAYLOAD", "order must be integer")
    
    if not patch:
        return _err("ERR_INVALID_PAYLOAD", "no changes")
    
    try:
        ok = work_repo.update_work(work_id, patch, by={"role": "admin"})
        if not ok:
            return _err("ERR_NOT_FOUND", "work not found")
        doc = work_repo.find_by_id(work_id)
    except work_repo.RepoError as e:
        return _err(e.code, e.message)
    


@bp.patch("/<work_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def patch_work(work_id: str) -> Tuple[Dict[str, Any], int]:
    body = request.get_json(silent=True) or {}
    op = (body.get("op") or "").strip()
    if not op:
        return _err("ERR_INVALID_PAYLOAD", "op is required")
    
    try:
        if op == "toggle_visible":
            if "value" in body:
                new_val = bool(body.get("value"))
            else:
                cur = work_repo.find_by_id(work_id)
                if not cur:
                    return _err("ERR_NOT_FOUND", "work not found")
                new_val = not bool(cur.get("is_visible", True))
            ok = work_repo.update_work(work_id, {"is_visible": new_val}, by={"role": "admin"})
            if not ok:
                return _err("ERR_NOT_FOUND", "work not found")
            doc = work_repo.find_by_id(work_id)
            return _ok(doc or {})
        
        if op == "set_order":
            try:
                value = int(body.get("value"))
            except Exception:
                return _err("ERR_INVALID_PAYLOAD", "value must be integer")
            ok = work_repo.update_work(work_id, {"order": value}, by={"role": "admin"})
            if not ok:
                return _err("ERR_NOT_FOUND", "work not found")
            doc = work_repo.find_by_id(work_id)
            return _ok(doc or {})
        
        return _err("ERR_INVALID_PAYLOAD", "unknown op")
    except work_repo.RepoError as e:
        return _err(e.code, e.message)
    

@bp.delete("/<work_id>")
@apply_rate_limit
@require_admin
@csrf_protect
def delete_work(work_id: str) -> Tuple[Dict[str, Any], int]:
    try:
        ok = work_repo.delete_work(work_id, by={"role": "admin"})
        if not ok:
            return _err("ERR_NOT_FOUND", "work not found")
        return _ok({"deleted": True})
    except work_repo.RepoError as e:
        return _err(e.code, e.message)
    