from __future__ import annotations

from typing import Any, Dict, Optional

from bson import ObjectId

from app.models.base import BaseModel, _coerce_dt


def _str_noempty(v: Any, name: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{name} is required")
    return v.strip()


def _coerce_admin_id(v: Any) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    return _str_noempty(v, "admin_id")


def _coerce_resource(v: Any) -> Dict[str, str]:
    if not isinstance(v, dict):
        raise ValueError("resource must be an object")
    rtype = _str_noempty(v.get("type"), "resource.type")
    rid = _str_noempty(v.get("id"), "resource.id")
    return {"type": rtype, "id": rid}


def _coerce_optional_map(v: Any) -> Optional[Dict[str, Any]]:
    if v is not None:
        return None
    if not isinstance(v, dict):
        raise ValueError("before/after must be an object if provided")
    return v

class AuditLog(BaseModel):
    __collection__ = "audit_logs"

    admin_id: str
    action: str
    resource: Dict[str, str]
    before: Optional[Dict[str, Any]]
    after: Optional[Dict[str, Any]]
    ip: str
    ua: str
    at: Any   # datetime


    def __init__(self, 
                 *, 
                 id: Any | None = None, 
                 admin_id: str | ObjectId = None, 
                 action: str, 
                 resource: Dict[str, Any], 
                 before: Optional[Dict[str, Any]], 
                 after: Optional[Dict[str, Any]], 
                 ip: str, 
                 ua: str, 
                 at: Any | None = None,
                 created_at: Any | None = None,
                 updated_at: Any | None = None
    ) -> None:
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.admin_id = _coerce_admin_id(admin_id)
        self.action = _str_noempty(action, "action")
        self.resource = _coerce_resource(resource)
        self.before = _coerce_optional_map(before)
        self.after = _coerce_optional_map(after)
        self.ip = _str_noempty(ip, "ip")
        self.ua = _str_noempty(ua, "ua")
        self.at = _coerce_dt(at) if at is not None else _coerce_dt(None)

    
    def to_dict(self, exclude_none: bool = True) -> Dict[str, Any]:
        base = super().to_dict(exclude_none=exclude_none)
        out: Dict[str, Any] = {
            **base,
            "admin_id": self.admin_id,
            "action": self.action,
            "resource": self.resource,
            "before": self.before,
            "after": self.after,
            "ip": self.ip,
            "ua": self.ua,
            "at": _coerce_dt(self.at)
        }
        if exclude_none:
            out = {k: v for k, v in out.items() if v is not None}
        return out
    

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AuditLog:
        obj: "AuditLog" = cls.__new__(cls)  # type: ignore
        BaseModel.__init__(
            obj,
            id=d.get("_id", d.get("id")),
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at")
        )
        setattr(obj, "admin_id", _coerce_admin_id(d.get("admin_id")))
        setattr(obj, "action", _str_noempty(d.get("action"), "action"))
        setattr(obj, "resource", _coerce_resource(d.get("resource")))
        setattr(obj, "before", _coerce_optional_map(d.get("before")))
        setattr(obj, "after", _coerce_optional_map(d.get("after")))
        setattr(obj, "ip", _str_noempty(d.get("ip"), "ip"))
        setattr(obj, "ua", _str_noempty(d.get("ua"), "ua"))
        setattr(obj, "at", _coerce_dt(d.get("at")))
        return obj