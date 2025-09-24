from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from pymongo import ASCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.constants import LANG_KO, SUPPORTED_LANGS, UserRole
from app.models.base import BaseModel
from app.utils.phone import normalize_kr as normalize_phone

UTC = timezone.utc
COLLECTION = "users"

__all__ = [
    "COLLECTION",
    "ensure_indexes",
    "get_collection",
    "User",
]


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel([("email", ASCENDING)], name="uniq_email", unique=True, partialFilterExpression={"email": {"$type": "string"}}),
            IndexModel([("phone", ASCENDING)], name="uniq_phone", unique=True, partialFilterExpression={"phone": {"$type": "string"}}),
            IndexModel([("name", ASCENDING)], name="idx_name"),
        ]
    )


def _iso_to_utc(v: Any) -> datetime:
    if v is None:
        return v
    if isinstance(v, datetime):
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _norm_email(email: Optional[str]) -> Optional[str]:
    if email is None:
        return None
    e = email.strip().lower()
    return e or None


def _norm_lang(lang: Optional[str]) -> str:
    l = (lang or "").strip().lower()
    return l if l in SUPPORTED_LANGS else LANG_KO


def _norm_channels(ch: Optional[dict]) -> dict:
    base = {
        "email": {"enabled": False},
        "sms": {"enabled": False},
        "kakao": {"enabled": False},
    }
    if not isinstance(ch, dict):
        return base
    out = dict(base)
    for k in ("email", "sms", "kakao"):
        v = ch.get(k, {})
        if isinstance(v, dict):
            enabled = bool(v.get("enabled", False))
            out[k] = {"enabled": enabled}
            if k == "email" and v.get("verified_at") is not None:
                out[k]["verified_at"] = _iso_to_utc(v.get("verified_at"))
    return out


class User(BaseModel):
    def __init__(self, doc: Optional[dict[str, Any]] = None):
        super().__init__(doc or {})

    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        doc: dict[str, Any] = {}

        _id = payload.get("_id") or payload.get("id")
        if _id:
            doc["_id"] = ObjectId(str(_id)) if not isinstance(_id, ObjectId) else _id

        name = (payload.get("name") or "").strip()
        if name:
            doc["name"] = name

        email = _norm_email(payload.get("email"))
        if email:
            doc["email"] = email

        phone = payload.get("phone")
        if phone:
            doc["phone"] = normalize_phone(str(콜))

        role = str(payload.get("role") or UserRole.CUSTOMER)
        doc["role"] = role if role in (UserRole.CUSTOMER, UserRole.ADMIN) else UserRole.CUSTOMER

        doc["lang_pref"] = _norm_lang(payload.get("lang_pref"))

        doc["channels"] = _norm_channels(payload.get("channels"))

        consents = payload.get("consents") or {}
        c_out: dict[str, Any] = {}
        if consents.get("tos_at"):
            c_out["tos_at"] = _iso_to_utc(consents.get("tos_at"))
        if consents.get("privacy_at"):
            c_out["privacy_at"] = _iso_to_utc(consents.get("privacy_at"))
        if c_out:
            doc["consents"] = c_out

        if payload.get("last_login_at"):
            doc["last_login_at"] = _iso_to_utc(payload.get("last_login_at"))

        doc["is_active"] = bool(payload.get("is_active", True))

        return User.stamp_new(doc)

    @staticmethod
    def prepare_update(partial: dict[str, Any]) -> dict[str, Any]:
        upd: dict[str, Any] = {}
        if "name" in partial:
            upd["name"] = (partial.get("name") or "").strip()
        if "email" in partial:
            e = _norm_email(partial.get("email"))
            if e is not None:
                upd["email"] = e
            else:
                upd.pop("email", None)
        if "phone" in partial:
            p = partial.get("phone")
            if p:
                upd["phone"] = normalize_phone(str(p))
        if "role" in partial:
            r = str(partial.get("role") or "").strip()
            if r in (UserRole.CUSTOMER, UserRole.ADMIN):
                upd["role"] = r
        if "lang_pref" in partial:
            upd["lang_pref"] = _norm_lang(partial.get("lang_pref"))
        if "channels" in partial:
            upd["channels"] = _norm_channels(partial.get("channels"))
        if "consents" in partial:
            consents = partial.get("consents") or {}
            c_out: dict[str, Any] = {}
            if "tos_at" in consents and consents.get("tos_at") is not None:
                c_out["tos_at"] = _iso_to_utc(consents.get("tos_at"))
            if "privacy_at" in consents and consents.get("privacy_at") is not None:
                c_out["privacy_at"] = _iso_to_utc(consents.get("privacy_at"))
            upd["consents"] = c_out
        if "last_login_at" in partial and partial.get("last_login_at") is not None:
            upd["last_login_at"] = _iso_to_utc(partial.get("last_login_at"))
        if "is_active" in partial:
            upd["is_active"] = bool(partial.get("is_active"))
        return User.stamp_update(upd)
