from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from flask import Blueprint, request

from app.middleware.auth import apply_rate_limit, require_admin
from app.services import admin_service
from app.utils.phone import normalize_phone

bp = Blueprint("admin_search", __name__)

# ---- Spec constants --------------------------------------------------------
MAX_Q_LEN = 100
ALLOWED_SORT_FIELDS = {"created_at"}
DEFAULT_SORT = "created_at:desc"


# ---- Internal helpers --------------------------------------------------------
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


def _parse_page_size(page: str | None, size: str | None, max_size: int = 100) -> Tuple[int ,int]:
    try:
        p = int(page) if page is not None else 1
    except Exception:
        p = 1
    try:
        s = int(size) if size is not None else 20
    except Exception:
        s = 20
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > max_size:
        s = max_size
    return p, s


def _sanitize_q(q: str | None) -> str:
    if q is None:
        raise ValueError("q required")
    s = q.strip()
    if not s:
        raise ValueError("q required")
    if len(s) > MAX_Q_LEN:
        raise ValueError("q too long")
    # allow letters, digits, space, common seperators and email symbols
    if not re.match(r"^[A-Za-z0-9@\.\+\-\_\s]+$", s):
        raise ValueError("q contains invalid characters")
    return s


def _maybe_normalize_phone(term: str) -> str:
    try:
        # Heuristic: contains digits and possibly +/-
        if re.search(r"[0-9]", term):
            return normalize_phone(term)
    except Exception:
        pass
    return term


def _parse_sort(sort: str | None) -> Tuple[str, bool]:
    order = (sort or DEFAULT_SORT).strip().lower()
    if ":" in order:
        field, direction = order.split(":", 1)
    else:
        field, direction = order, "asc"
    if field not in ALLOWED_SORT_FIELDS:
        field = "created_at"
    desc = direction == "desc"
    return field, desc


def _sort_page_items(items: List[Dict[str, Any]], field: str, desc: bool) -> List[Dict[str, Any]]:
    key = (field or "created_at").strip()
    return sorted(items, key=lambda x: str(x.get(key, "")), reverse=desc)


# ---- Route --------------------------------------------------------
@bp.get("/")
@apply_rate_limit
@require_admin
def get_search_admin():
    try:
        raw_q = request.args.get("q")
        q = _sanitize_q(raw_q)
        # Normalize Korean mobile phone into +82-10-####-#### when possible
        q_norm = _maybe_normalize_phone(q)

        page, size = _parse_page_size(request.arg.get("page"), request.args.get("size"))
        sort_field, sort_desc = _parse_sort(request.args.get("sort"))

        # Delegate to service (repo-level pagination). Service returns {ok,data|error}
        svc_res = admin_service.search(q_norm, page=page, size=size)
        if not isinstance(svc_res, dict) or not svc_res.get("ok"):
            err = (svc_res.get("error") if isinstance(svc_res, dict) else {}) or {}
            return _err(err.get("code") or "ERR_INTERNAL", err.get("message") or "internal error")
        
        data = svc_res["data"]
        items = list(data.get("items") or [])
        total = int(data.get("total") or 0)

        # Best-effort sort within current page (primary sort is expected to be applied by repo)
        items = _sort_page_items(items, sort_field, sort_desc)

        return _ok({"items": items, "total": total, "page": page, "size": size})
    except ValueError as e:
        return _err("ERR_INVALID_PAYLOAD", str(e))
    except Exception as e:
        return _err("ERR_INTERNAL", str(e))