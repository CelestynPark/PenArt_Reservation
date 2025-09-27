from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.repositories.common import get_collection, in_txn, map_pymongo_error
from app.utils.time import now_utc, isoformat_utc

__all__ = ["normalize_phone_for_query", "search_admin"]


# ---- helpers ----
def _coll_users() -> Collection:
    return get_collection("users")


def _coll_bookings() -> Collection:
    return get_collection("bookings")


def _coll_orders() -> Collection:
    return get_collection("orders")


def _now_iso() -> str:
    return isoformat_utc(now_utc())


class RepoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# Prefer the global normalizer; keep a KR fallback for tests/min envs.
try:
    from app.utils.phone import normalize_phone as _normalize_phone # type: ignore[attr-defined]
except Exception:   # pragma: no cover
    _normalize_phone = None    # type: ignore


def normalize_phone_for_query(input_phone: str) -> str:
    if not isinstance(input_phone, str) or not input_phone.strip():
        raise RepoError("ERR_INVALID_PAYLOAD", "phone required")
    if _normalize_phone is not None:
        try:
            return _normalize_phone(input_phone)    # type: ignore[misc]
        except Exception as e:  # pragma: no cover
            raise RepoError("ERR_INVALID_PAYLOAD", str(e))
    # Fallback for KR mobiles -> +82-10-####-####
    s = re.sub(r"[^\d]", "", input_phone)
    if s.startswith("82"):
        s = s[2:]
    if s.startswith("0"):
        s = s[1:]
    if not s.startswith("10"):
        raise RepoError("ERR_INVALID_PAYLOAD", "invalid KR phone")
    if len(s) not in (9, 10, 11):
        raise RepoError("ERR_INVALID_PAYLOAD", "invalid KR phone length")
    if len(s) == 9:
        s = "0" + s
    mid = s[2:6]
    tail = s[6:]
    return f"+82-10-{mid}-{tail}"


# ---- core search ----
_CODE_RE = re.compile(r"^(BKG/ORD)-\d{8}-[A-Z0-9]{6}$", re.IGNORECASE)


def _is_code(q: str) -> bool:
    return bool(_CODE_RE.match(q))


def _safe_prefix_regex(text: str) -> Dict[str, Any]:
    return {"$regex": f"^{re.escape(text)}", "$options": "i"}


def _as_id(obj: Any) -> str:
    try:
        from bson import ObjectId   # lazy import
        if isinstance(obj, ObjectId):
            return str(obj)
    except Exception:   # pragma: no cover
        pass
    return str(obj)


def _booking_result(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "booking",
        "id": _as_id(doc.get("_id")),
        "code": doc.get("code"),
        "customer_id": _as_id(doc.get("customer_id")) if doc.get("customer_id") else None,
        "start_at": doc.get("start_at")
    }


def _order_result(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "order",
        "id": _as_id(doc.get("_id")),
        "code": doc.get("code"),
        "customer_id": _as_id(doc.get("customer_id")) if doc.get("customer_id") else None,
        "status": doc.get("status"),
        "created_at": doc.get("created_at")
    }


def _user_result(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "user",
        "id": _as_id(doc.get("_id")),
        "name": doc.get("name"),
        "phone": doc.get("phone"),
        "email": (doc.get("email") or "").lower() if doc.get("email") else None
    }


def _dedupe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[Tuple[str, str]] = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        k = (it.get("type", ""), it.get("id", ""))
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def search_admin(q: str, limit: int = 20) -> Dict[str, Any]:
    try:
        if not isinstance(q, str) or not q.strip():
            raise RepoError("ERR_INVALID_PAYLOAD", "q required")
        try:
            lim = int(limit)
        except Exception:
            raise RepoError("ERR_INVALID_PAYLOAD", "limit must be int")
        if lim <= 0 or lim > 100:
            raise RepoError("ERR_INVALID_PAYLOAD", "limit must be 1..100")
        
        q_str = q.strip()
        results: List[Dict[str, Any]] = []

        # 1) Exact code hits (always top)
        if _is_code(q_str):
            code = q_str.upper()
            try:
                b = _coll_bookings().find_one({"code": code}, {"_id": 1, "code": 1, "customer_id": 1, "start_at": 1})
                if b:
                    results.append(_booking_result(b))
                o = _coll_orders().find_one({"code": code}, {"_id": 1, "code": 1, "customer_id": 1, "created_at": 1})
                if o:
                    results.append(_order_result(o))
            except PyMongoError as e:
                err = map_pymongo_error(e)
                return {"ok": False, "error": err}
            results = _dedupe(results)
            return {"ok": True, "data": {"items": results[:lim], "total": len(results)}}
        
        # 2) Non-code: exact email / exact phone / name prefix
        email_like = "@" in q_str
        phone_like = bool(re.search(r"[\d\-\+\s]", q_str)) and not email_like and not q_str.isalpha()
        name_like = not email_like and not phone_like

        # exact email
        if email_like and len(results) < lim:
            try:
                u = _coll_users().find_one({"email": q_str.strip().lower()}, {"_id": 1, "name": 1, "phone": 1, "email": 1})
                if u:
                    results.append(_user_result(u))
            except PyMongoError as e:
                err = map_pymongo_error(e)
                return {"ok": False, "error": err}
            
        # exact phone
        if phone_like and len(results) < lim:
            try:
                normalized = normalize_phone_for_query(q_str)
                u = _coll_users().find_one({"phone": normalized}, {"_id": 1, "name": 1, "phone": 1, "email": 1})
                if u:
                    results.append(_user_result(u))
            except RepoError as e:
                # treat as no phone match rather than failing whole search if input can't normalize
                pass
            except PyMongoError as e:
                err = map_pymongo_error(e)
                return {"ok": False, "error": err}
            
        # name prefix (case-insensitive)
        if name_like and len(results) < lim:
            try:
                cur = _coll_users().find_one(
                    {"name": _safe_prefix_regex(q_str)},
                    {"_id": 1, "name": 1, "phone": 1, "email": 1}
                ).limit(lim)
                results.extend(_user_result(d) for d in cur)
            except PyMongoError as e:
                err = map_pymongo_error(e)
                return {"ok": False, "error": err}
            
        # 3) Addtionally, allow partial booking/order code prefix (BKG-/ORD- or raw prefix)
        if len(results) < lim:
            prefix = q_str.upper()
            conds = []
            if prefix.startswith("BKG-") or prefix.startswith("ORD-"):
                conds.append({"code": {"$regex": f"^{re.escape(prefix)}"}})
            elif re.match(r"^[A-Z0-9\-]{3,}$", prefix):
                conds.append({"code": {"$regex": f"^{re.escape(prefix)}"}})
            
            if conds:
                try:
                    bcur = _coll_bookings().find(
                        conds[0],
                        {"_id": 1, "code": 1, "customer_id": 1, "start_at": 1}
                    ).limit(lim)
                    ocur = _coll_orders().find(
                        conds[0],
                        {"_id": 1, "code": 1, "customer_id": 1, "status": 1, "created_at": 1}
                    ).limit(lim)
                    results.extend(_booking_result(d) for d in bcur)
                    results.append(_order_result(d) for d in ocur)
                except PyMongoError as e:
                    err = map_pymongo_error(e)
                    return {"ok": False, "error": err}
                
        results = _dedupe(results)
        if len(results) > lim:
            results = results[lim]
        return {"ok": True, "data": {"items": results, "total": len(results)}}
    except RepoError as e:
        return {"ok": False, "error": {"code": e.code, "messeg": e.message}}
    except Exception:
        return {"ok": False, "error": {"code": "ERR_INTERNAL", "message": "internal error"}}