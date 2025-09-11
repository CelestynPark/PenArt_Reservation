from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from flask import g, request

from app.core.constants import DEFAULT_LANG

_SUPPORTED = {"ko", "en"}


def _normalize_lang(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    v = v.strip().lower().replace("_", "-")
    if v in _SUPPORTED:
        return v
    # Accept forms like "en-US", "ko-KR"
    base = v.split("-", 1)[0]
    return base if base in _SUPPORTED else None


def get_lang(preferred: str | None = None) -> str:
    for cand in (
        preferred,
        getattr(g, "lang", None),
        request.cookies.get("lang") if request else None,
        DEFAULT_LANG,
        "ko",
    ):
        norm = _normalize_lang(cand)
        if norm:
            return norm
    return "ko"


def pick_i18n(doc: Mapping[str, Any], key_prefix: str, lang: str | None = None) -> str:
    eff = get_lang(lang)
    key = f"{key_prefix}_i18n"
    bundle = doc.get(key) if isinstance(doc, Mapping) else None
    if not isinstance(bundle, Mapping):
        return ""
    val = bundle.get(eff)
    if isinstance(val, str) and val.strip():
        return val
    val_ko = bundle.get("ko")
    return val_ko if isinstance(val_ko, str) else ""


_MESSAGES: Dict[str, Dict[str, str]] = {
    "ko": {
        "error.invalid_payload": "요청 형식이 올바르지 않습니다.",
        "error.unauthorized": "인증이 필요합니다.",
        "error.forbidden": "접근 권한이 없습니다.",
        "error.not_found": "요청하신 항목을 찾을 수 없습니다.",
        "error.rate_limited": "요청이 너무 많습니다. 잠시 후 다시 시도해주세요.",
        "booking.cutoff.change": "정책상 해당 시간은 변경이 불가합니다.",
        "booking.cutoff.cancel": "정책상 해당 시간은 취소가 불가합니다.",
        "order.expired": "입금 기한이 만료되었습니다. 주문이 취소 처리됩니다.",
        "empty.content": "아직 등록된 콘텐츠가 없습니다.",
        "gallery.load_error": "이미지를 불러오지 못했습니다. 새로고침 해주세요.",
    },
    "en": {
        "error.invalid_payload": "The request payload is invalid.",
        "error.unauthorized": "Authentication required.",
        "error.forbidden": "You do not have permission.",
        "error.not_found": "The requested item was not found.",
        "error.rate_limited": "Too many requests. Please try again later.",
        "booking.cutoff.change": "Changes are not allowed by policy for this time.",
        "booking.cutoff.cancel": "Cancellation is not allowed by policy for this time.",
        "order.expired": "The payment window has expired. Your order will be canceled.",
        "empty.content": "No content has been published yet.",
        "gallery.load_error": "Failed to load images. Please refresh.",
    },
}


def t(key: str, lang: str | None = None, **params: Any) -> str:
    eff = get_lang(lang)
    msg = (_MESSAGES.get(eff) or {}).get(key)
    if not msg:
        msg = (_MESSAGES.get("ko") or {}).get(key) or key
    try:
        return msg.format(**params) if params else msg
    except Exception:
        return msg  # do not raise if formatting fails


def i18n_wrap(payload: Dict[str, Any], lang: str | None = None) -> Dict[str, Any]:
    eff = get_lang(lang)
    out = dict(payload or {})
    out["i18n"] = {"lang": eff}
    return out
