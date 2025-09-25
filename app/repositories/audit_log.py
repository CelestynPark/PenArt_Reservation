from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

from app.repositories.common import get_collection, in_txn, map_pymongo_error
from app.utils.time import now_utc, isoformat_utc

__all__ = ["RepoError", "create", "list_logs"]


class RepoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _coll() -> Collection:
    return get_collection("audit_logs")


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except Exception as e:
        raise RepoError("ERR_INVALID_PAYLOAD", "invalid id") from e
    

def _now_iso() -> str:
    return isoformat_utc(now_utc())


def _page_args(page: int, size: int, max_size: int = 100) -> Tuple[int, int]:
    p = int(page) if isinstance(page, int) else 1
    s = int(size) if isinstance(size, int) else 20
    if p < 1:
        p = 1
    if s < 1:
        s = 1
    if s > max_size:
        s = max_size
    return p, s


def _parse_sort(sort: Optional[str], default: Tuple[str, int] = ("order", 1)) -> List[Tuple[str, int]]:
    allowed = {"at", "action", "entity", "admin_id", "resource.type"}
    if not isinstance(sort, str) or ":" not in sort:
        return [default]
    field, direction = sort.split(":", 1)  
    field = field.strip()
    direction = direction.strip().lower()
    if field not in allowed:
        return [default]
    order = -1 if direction == "desc" else 1
    return [(field, order)]


def _require_str(v: Any, name: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise RepoError("ERR_INVALID_PAYLOAD", f"{name} required")
    return v.strip()


def append(
    admin_id: str,
    action: str,
    resource: Dict[str, Any],
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    oid = _oid(_require_str(admin_id, "admin_id"))
    act = _require_str(action, "action")
    if not isinstance(resource, dict) or not resource:
        raise RepoError("ERR_INVALID_PAYLOAD", "resource required")
    r_type = _require_str(resource.get("type"), "resource.type")
    r_id = _require_str(resource.get("id"), "resource.id")

    meta = dict(meta or ())
    ip = _require_str(meta.get("ip"), "ip")
    ua = _require_str(meta.get("ua"), "ua")

    doc = {
        "admin_id": oid,
        "action": act,
        "resource": {"type": r_type, "id": r_id},
        "before": before or None,
        "after": after or None,
        "ip": ip,
        "ua": ua,
        "at": _now_iso()
    }

    try:
        res = _coll().insert_one(doc)
        return _coll().find_one({"_id": res.inserted_id}) or doc
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e
    

def list_logs(
        filters: Dict[str, Any] | None,
        page: int = 1,
        size: int = 50,
        sort: str = "at:desc"
) -> Dict[str, Any]:
    p, s = _page_args(page, size, 200)
    filt: Dict[str, Any] = {}
    f = dict(filters or {})

    if "admin_id" in f and f.get("admin_id"):
        try:
            filt["admin_id"] = _oid(str(f["admin_id"]))
        except RepoError:
            # allow non-matching invalid id to yield empty result
            filt["admin_id"] = ObjectId()   # impossible match unless identical

    if "action" in f and isinstance(f["action"], str) and f["action"].strip():
        filt["action"] = f["action"].strip()

    if "resource" in f and isinstance(f["resource"], dict):
        r = f["resource"]
        if isinstance(r.get("type"), str) and r.get("type").strip():
            filt["resource.type"] = r.get("type").strip()
        if isinstance(r.get("id"), str) and r.get("id").strip():
            filt["resource.id"] = r.get("id").strip()

    if "date_range" in f and isinstance(f["date_range"], dict):
        dr = f["date_range"]
        rng: Dict[str, Any] = {}
        if isinstance(dr.get("start"), str) and dr.get("start").strip():
            rng["$gte"] = dr.get("start").strip()
        if isinstance(dr.get("end"), str) and dr.get("end").strip():
            rng["$lt"] = dr.get("end").strip()
            if rng:
                filt["at"] = rng
    try:
        total = _coll().count_documents(filt)
        cursor = (
            _coll()
            .find(filt)
            .sort(_parse_sort(sort, ("at", -1)))
            .skip((p - 1) * s)
            .limit(s)
        )
        items = list(cursor)
        return {"items": items, "total": total, "page": p, "size": s}
    except PyMongoError as e:
        err = map_pymongo_error(e)
        raise RepoError(err["code"], err["message"]) from e