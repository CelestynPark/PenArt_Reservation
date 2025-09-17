from __future__ import annotations

from typing import Any, Optional

from pymongo import ASCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.models.base import BaseModel

COLLECTION = "services"

__all__ = ["COLLECTION", "get_collection", "ensure_indexes", "Service"]


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("is_active", ASCENDING), ("oerder", ASCENDING)], name="idx_active_order")
        ]
    )   


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _is_noempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _norm_i18n_text(d: Any, *, required_ko: bool) -> Optional[dict[str, str]]:
    if not isinstance(d, dict):
        raise ValueError("invalid i18n payload")
    ko = d.get("ko")
    en = d.get("en")
    if required_ko and not _is_noempty_str(ko):
        raise ValueError("ko is requried")
    out: dict[str, str] = {"ko": ko.strip()}
    if _is_str(en) and en.strip() != "":
        out["en"] = en.strip()
    return out


def _as_int_noneg(v: Any) -> int:
    if isinstance(v, bool):
        raise ValueError("invalid int")
    try:
        n = int(v)
    except Exception:
        raise ValueError("invalid int")
    if n < 0:
        raise ValueError("must be >= 0")
    return n


def _as_int_pos(v: Any) -> int:
    n = _as_int_noneg(v)
    if n <= 0:
        raise ValueError("must be > 0")
    return n


def _norm_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    return bool(v)


def _norm_images(images: Any) -> list[str]:
    if images is None:
        return []
    if not isinstance(images, list):
        raise ValueError("invalid images")
    out: list[str] = []
    for v in images:
        if _is_noempty_str(v):
            out.append(v.strip())
    return out


def _norm_policy(p: Any, *, defaults: bool = True) -> dict[str, int]:
    keys = {"cancel_before_hours", "change_before_hours", "no_show_after_min"}
    if p is None:
        return {k: 0 for k in keys} if defaults else {}
    if not isinstance(p, dict):
        raise ValueError("invalid policy")
    out: dict[str, int] = {}
    for k in keys:
        if k in p:
            out[k] = _as_int_noneg(p[k])
        elif defaults:
            out[k] = 0
    return out


class Service(BaseModel):
    def __init__(self, doc: Optional[dict[str, Any]] = None):
        super().__init__(doc or {})

    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        doc: dict[str, Any] = {}

        # Required KO texts
        if "name_i18n" not in payload:
            raise ValueError("name_i18n.ko is required")
        if "description_i18n" not in payload:
            raise ValueError("description_i18n.ko is requried")
        
        doc["name_i18n"] = _norm_i18n_text(payload.get("name_i18n"), required_ko=True)
        doc["description_i18n"] = _norm_i18n_text(payload.get("description_i18n"), required_ko=True)

        # Optional i18n sections
        if "prerequisites_i18n" in payload:
            doc["prerequisites_i18n"] = _norm_i18n_text(payload.get("prerequisites_i18n"), required_ko=True)
        if "materials_i18n" in payload:
            doc["materials_i18n"] = _norm_i18n_text(payload.get("materials_i18n"), required_ko=True)

        # Scalers
        if "level" in payload and _is_noempty_str(payload["level"]):
            doc["level"] = payload["level"].strip()

        if "duration_min" in payload:
            raise ValueError("duration min is required")
        doc["duration_min"] = _as_int_pos(payload.get("duration_min"))

        # Arrays
        doc["images"] = _norm_images(payload.get("images"))

        # Policy
        doc["policy"] = _norm_policy(payload.get("policy"), defaults=True)

        # Flags / ordering
        doc["auto_confirm"] = _norm_bool(payload.get("auto_confirm"), default=True)
        doc["is_active"] = _norm_bool(payload.get("is_active"), default=True)
        doc["is_featured"] = _norm_bool(payload.get("is_featured"), default=False)
        order_val = payload.get("order", 0)
        doc["order"] = _as_int_noneg(order_val)

        return Service.stamp_new(doc)
    
    @staticmethod
    def prepare_update(partial: dict[str, Any]) -> dict[str, Any]:
        upd: dict[str, Any] = {}

        if "name_i18n" in partial:
            upd["name_i18n"] = _norm_i18n_text(partial.get("name_i18n"), required_ko=True)
        
        if "description_i18n" in partial:
            upd["description_i18n"] = _norm_i18n_text(partial.get("description_i18n"), required_ko=True)
        
        if "prerequisites_i18n" in partial:
            upd["prerequisites_i18n"] = _norm_i18n_text(partial.get("prerequisites_i18n"), required_ko=True)
        
        if "materials_i18n" in partial:
            upd["materials_i18n"] = _norm_i18n_text(partial.get("materials_i18n"), required_ko=True)
        
        if "level" in partial and _is_str(partial.get("level")):
            upd["level"] = partial.get(("level") or "").strip()

        if "duration_min" in partial:
            upd["duration_min"] = _as_int_pos(partial.get("duration_min"))

        if "images" in partial:
            upd["images"] = _norm_images(partial.get("images"))
        
        if "policy" in partial:
            # Only set provided keys, no defaults on update
            pol = _norm_policy(partial.get("policy"), default=False)
            if pol:
                upd["policy"] = pol

        if "auto_confirm" in partial:
            upd["auto_confirm"] = _norm_bool(partial.get("auto_confirm"))
        
        if "is_active" in partial:
            upd["is_active"] = _norm_bool(partial.get("is_active"))
        
        if "is_featured" in partial:
            upd["is_featured"] = _norm_bool(partial.get("is_featured"))
        
        if "order" in partial:
            upd["order"] = _as_int_noneg(partial.get("order"))

        return Service.stamp_update(upd)
    