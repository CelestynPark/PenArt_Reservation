from __future__ import annotations

from typing import Any, Optional

from pymongo import ASCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.models.base import BaseModel

COLLECTION = "studio"

__all__ = ["COLLECTION", "ensure_indexes", "get_collection", "Studio"]


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("is_active", ASCENDING)], name="idx_active"),
        ]
    )


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _is_nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _norm_i18n_text(d: Any, *, require_ko: bool = True) -> dict[str, str]:
    if not isinstance(d, dict):
        raise ValueError("invalid i18n payload")
    ko = d.get("ko")
    en = d.get("en")
    if require_ko and not _is_nonempty_str(ko):
        raise ValueError("ko is required")
    out: dict[str, str] = {"ko": ko.strip()}
    if _is_str(en) and en.strip() != "":
        out["en"] = en.strip()
    return out


def _as_float(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and v.strip() != "":
        try:
            return float(v)
        except Exception:
            pass
    raise ValueError("invalid float")


def _norm_address(addr: Any) -> dict[str, Any]:
    if not isinstance(addr, dict):
        raise ValueError("invalid address")
    out: dict[str, Any] = {}
    if "text" in addr and _is_str(addr["text"]):
        out["text"] = addr["text"].strip()
    if "lat" in addr or "lng" in addr:
        lat = _as_float(addr.get("lat"))
        lng = _as_float(addr.get("lng"))
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lng <= 180.0):
            raise ValueError("invalid coordinates")
        out["lat"] = lat
        out["lng"] = lng
    return out


def _norm_styles(styles: Any) -> list[str]:
    if styles is None:
        return []
    if not isinstance(styles, list):
        raise ValueError("styles must be list")
    out: list[str] = []
    for s in styles:
        if _is_nonempty_str(s):
            out.append(s.strip())
    return out


def _norm_contact(contact: Any) -> dict[str, Any]:
    if contact is None:
        return {}
    if not isinstance(contact, dict):
        raise ValueError("invalid contact")
    out: dict[str, Any] = {}
    if "phone" in contact and _is_str(contact["phone"]):
        out["phone"] = contact["phone"].strip()
    if "email" in contact and _is_str(contact["email"]):
        out["email"] = contact["email"].strip().lower()
    if "sns" in contact:
        out["sns"] = contact["sns"]
    return out


def _norm_map(m: Any) -> dict[str, Any]:
    if m is None:
        return {}
    if not isinstance(m, dict):
        raise ValueError("invalid map")
    out: dict[str, Any] = {}
    if "naver_client_id" in m and _is_nonempty_str(m["naver_client_id"]):
        out["naver_client_id"] = m["naver_client_id"].strip()
    return out


class Studio(BaseModel):
    def __init__(self, doc: Optional[dict[str, Any]] = None):
        super().__init__(doc or {})

    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        doc: dict[str, Any] = {}

        # Required/primary fields
        if "bio_i18n" not in payload:
            raise ValueError("bio_i18n.ko is required")
        if "notice_i18n" not in payload:
            raise ValueError("notice_i18n.ko is required")

        if "name" in payload and _is_nonempty_str(payload["name"]):
            doc["name"] = payload["name"].strip()

        doc["bio_i18n"] = _norm_i18n_text(payload.get("bio_i18n"), require_ko=True)
        doc["notice_i18n"] = _norm_i18n_text(payload.get("notice_i18n"), require_ko=True)

        if "avatar" in payload and _is_nonempty_str(payload["avatar"]):
            doc["avatar"] = payload["avatar"].strip()

        doc["styles"] = _norm_styles(payload.get("styles"))

        if "address" in payload:
            doc["address"] = _norm_address(payload.get("address"))

        if "hours" in payload:
            # Stored as-is (string or simple structure), time zone agnostic per spec
            doc["hours"] = payload.get("hours")

        if "contact" in payload:
            doc["contact"] = _norm_contact(payload.get("contact"))

        if "map" in payload:
            doc["map"] = _norm_map(payload.get("map"))

        doc["is_active"] = bool(payload.get("is_active", True))

        return Studio.stamp_new(doc)

    @staticmethod
    def prepare_update(partial: dict[str, Any]) -> dict[str, Any]:
        upd: dict[str, Any] = {}

        if "name" in partial and _is_str(partial.get("name")):
            upd["name"] = (partial.get("name") or "").strip()

        if "bio_i18n" in partial:
            upd["bio_i18n"] = _norm_i18n_text(partial.get("bio_i18n"), require_ko=True)

        if "notice_i18n" in partial:
            upd["notice_i18n"] = _norm_i18n_text(partial.get("notice_i18n"), require_ko=True)

        if "avatar" in partial and _is_str(partial.get("avatar")):
            val = (partial.get("avatar") or "").strip()
            if val:
                upd["avatar"] = val

        if "styles" in partial:
            upd["styles"] = _norm_styles(partial.get("styles"))

        if "address" in partial:
            upd["address"] = _norm_address(partial.get("address"))

        if "hours" in partial:
            upd["hours"] = partial.get("hours")

        if "contact" in partial:
            upd["contact"] = _norm_contact(partial.get("contact"))

        if "map" in partial:
            upd["map"] = _norm_map(partial.get("map"))

        if "is_active" in partial:
            upd["is_active"] = bool(partial.get("is_active"))

        return Studio.stamp_update(upd)
