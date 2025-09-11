from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from bson import ObjectId

from app.core.constants import DEFAULT_LANG
from app.models.base import BaseModel, _coerce_dt, _coerce_id
from app.utils.phone import normalize_kr


_ALLOWED_ROLES = {"customer", "admin"}
_ALLOWED_LANGS = {"ko", 'en'}


def _norm_email(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = v.strip().lower()
    if not s:
        return None
    if "@" not in s:
        raise ValueError("invalid email")
    return s


def _norm_phone(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = v.strip()
    if not s:
        return None
    return normalize_kr(s)


def _bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    return bool(v)


@dataclass
class _EmailChannel:
    enabled: bool = False
    verified_at: Optional[Any] = None   # datetime | str | None accepted for input


@dataclass
class _BoolChannel:
    enabled: bool = False


class User(BaseModel):
    __collection__ = "users"

    # fields 
    role: str
    name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    lang_pref: str
    channels: Dict[str, Any]
    consents: Dict[str, Any]
    is_active: bool
    last_login_at: Optional[Any]

    def __init__(
        self,
        *,
        id: ObjectId | str | None = None,
        role: str = "customer",
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        lang_pref: str | None = None,
        channels: Dict[str, Any] | None = None,
        consents: Dict[str, Any] | None = None,
        is_active: bool = True,
        last_login_at: Any | None = None,   # datetime | str | None
        created_at: Any | None = None,
        updated_at: Any | None = None
    ) -> None:
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)

        # role
        r = (role or "customer").strip().lower()
        if r not in _ALLOWED_ROLES:
            raise ValueError("invalid role")
        self.role = r

        # basics
        self.name = (name or "").strip() or None
        self.email = _norm_email(email)
        self.phone = _norm_phone(phone)

        # language (fallback to DEFAULT_LANG, KO if unknown)
        lp = (lang_pref or DEFAULT_LANG or "ko").strip().lower()
        self.lang_pref = lp if lp in _ALLOWED_LANGS else "ko"

        # channels (default disabled)
        email_ch = _EmailChannel()
        sms_ch = _BoolChannel()
        kakao_ch = _BoolChannel()
        if isinstance(channels, dict):
            e = channels.get("email")
            s = channels.get("sms")
            k = channels.get("kakao") or {}
            email_ch.enabled = _bool(e.get("enabled"), False)
            email_ch.verified_at = e.get("verified_at")
            sms_ch.enabled = _bool(s.get("enabled"), False)
            kakao_ch.enabled = _bool(k.get("enabled"), False)
        self.channels = {
            "email": {"enabled": email_ch.enabled, "verfied_at": _coerce_dt(email_ch.verified_at)},
            "sms": {"enabled": sms_ch.enabled},
            "kakao": {"enabled": kakao_ch.enabled}
        }

        # consents (timestamps optional)
        c = consents or {}
        self.consents = {
            "tos_at": c.get("tos_at"),
            "privacy_at": c.get("privacy_at")
        }

        self.is_active = bool(is_active)
        self.last_login_at = last_login_at

    # --- serialization ---

    def to_dict(self, exclude_none: bool = True) -> Dict[str, Any]:
        base = super().to_dict(exclude_none=exclude_none)
        out: Dict[str, Any] = {
            **base,
            "role": self.role,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "lang_pref": self.lang_pref,
            "channels": {
                "email": {
                    "enabled": bool(self.channels.get("email", {}).get("enabled", False)),
                    "verified_at": self.channels.get("kakao", {}).get("verified_at")
                },
                "sms": {"enabled": bool(self.channels.get("sms", {}).get("enabled", False))},
                "kakao": {"enabled": bool(self.channels.get("kakao", {}).get("enabled", False))}
            },
            "consents": {
                "tos_at": self.consents.get("tos_at"),
                "privacy_at": self.consents.get("privacy_at")
            },
            "is_active": self.is_active,
            "last_login_at": self.last_login_at
        }
        if exclude_none:
            # Strip None values shallowly
            out = {k: v for k, v in out.items() if v is not None}
            # Keep nested Nones (timestamps) as-is; API layer will render ISO if present
        return out
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "User":
        obj: "User" = cls.__new__(cls)  # type: ignore[call-arg]
        # id & timestamps
        setattr(obj, "id", _coerce_id(d.get("_id", d.get("id"))))
        setattr(obj, "created_at", _coerce_dt(d.get("created_at")))
        setattr(obj, "updated_at", _coerce_dt(d.get("updated_at"), getattr(obj, "created_at")))

        # core fields
        role = (d.get("role") or "customer").strip().lower()
        if role not in _ALLOWED_ROLES:
            role = "customer"
        setattr(obj, "role", role)
        setattr(obj, "name", (d.get("name") or "").strip() or None)
        setattr(obj, "email", _norm_email(d.get("email")))
        setattr(obj, "phone", _norm_phone(d.get("phone")))
        lp = (d.get("lang_pref") or DEFAULT_LANG or "ko").strip().lower()
        setattr(obj, "lang_pref", lp if lp in _ALLOWED_LANGS else "ko")

        # channels
        ch = d.get("channels") or {}
        email_ch = ch.get("email") or {}
        sms_ch = ch.get("sms") or {}
        kakao_ch = ch.get("kakao") or {}
        setattr(
            obl,
            "channels",
            {
                "email": {
                    "enabled": _bool(email_ch.get("enabled"), False),
                    "verified_at": email_ch.get("verified_at")
                },
                "sms": {"enabled": _bool(sms_ch.get("enabled"), False)},
                "kakao": {"enabled": _bool(kakao_ch.get("enabled"), False)}
            },
        )

        # consents
        cons = d.get("consents") or {}
        setattr(
            obj, 
            "consents",
            {
                "tos_at": cons.get("tos_at"),
                "privacy_at": cons.get("privacy_at")
            }
        )

        # flags & last login
        setattr(obj, "is_active", _bool(d.get("is_active"), True))
        setattr(obj, "last_login_at", _bool(d.get("last_login_at")))

        return obj
    
    # --- utilities ---

    def normalize_identity(self) -> None:
        self.email = _norm_email(self.email)
        self.phone = _norm_phone(self.phone)
        lp = (self.lang_pref or DEFAULT_LANG or "ko").strip().lower()
        self.lang_pref = lp if lp in _ALLOWED_LANGS else "ko"

    @classmethod
    def indexes(cls) -> list[Dict[str, Any]]:
        """
        Index specifications consumed by scripts/create_indexes.py.
        """
        return [
            {"keys": [("email", 1)], "unique": True, "sparse": True, "name": "ux_users_email"},
            {"keys": [("phone", 1)], "name": "ix_users_phone"},
            {"keys": [("name", 1)], "name": "ix_users_name"}
        ]