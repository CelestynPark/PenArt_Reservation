from __future__ import annotations

from typing import Any, Dict

from bson import ObjectId

from app.extensions import get_mongo
from app.repositories.common import apply_paging
from app.utils.time import now_utc
from app.models.audit_log import AuditLog


def _coll():
    return get_mongo()["audit_logs"]


def _noempty_str(v: Any, name: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{name} is required")
    return v.strip()


def _normalize(doc: Dict[str, Any]) -> Dict[str, Any]:
    if not doc:
        return {}
    out = dict(doc)
    _id = out.pop("_id", None)
    if _id is not None:
        out["id"] = str(_id) if isinstance(_id, ObjectId) else _id
    return out


def write(entry: dict) -> dict:
    if not isinstance(entry, dict):
        raise ValueError("entry must be an object")
    _noempty_str(entry.get("action"), "action")
    res = entry.get("resource")
    if not isinstance(res, dict) or not res.get("type") or not res.get("id"):
        raise ValueError("resource.type and resource.id are requried")
    _noempty_str(entry.get("admin_id"), "admin_id")
    _noempty_str(entry.get("ip"), "ip")
    _noempty_str(entry.get("ua"), "ua")
    if entry.get("at") is None:
        raise ValueError("at is required")
    
    now = now_utc()
    doc = AuditLog(
        admin_id=entry["admin_id"],
        action=entry["action"],
        resource={"type": str(res["type"]).strip(), "id": str(res["id"]).strip()},
        before=entry.get("before"),
        after=entry.get("after"),
        ip=entry.get("ip"),
        ua=entry.get("ua"),
        at=entry.get("at"),
        created_at=now,
        updated_at=now
    ).to_dict()
    _coll().insert_one(doc)
    return _normalize(doc)


def list_by_resource(resource_type: str, resource_id: str, page:int, size: int, sort: tuple[str, str]) -> dict:
    rtype = _noempty_str(resource_type, "resource_type")
    rid = _noempty_str(resource_id, "resource_id")
    cursor = _coll().find({"resource.type": rtype, "resource.id": rid})
    s = sort if sort and isinstance(sort, tuple) else ("created_at", "desc")
    data = apply_paging(cursor, page, size, s)
    data["items"] = [_normalize(doc) for doc in data["items"]]
    return data