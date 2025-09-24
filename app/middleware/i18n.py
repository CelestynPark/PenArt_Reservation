from __future__ import annotations

import json
from typing import Any, Dict, Optional

from flask import g, request, Response

from app.services.i18n_service import resolve_lang

__all__ = ["i18n_before_request", "i18n_after_request", "get_current_lang"]


def _pick_lang() -> str:
    q = request.args.get("lang")
    c = request.cookies.get("lang")
    h = request.headers.get("Accept-Language")
    return resolve_lang(q, c, h)


def i18n_before_request() -> None:
    g.lang = _pick_lang()


def _inject_i18n(envelope: Dict[str, Any], lang: str) -> Dict[str, Any]:
    if not isinstance(envelope, dict):
        return envelope
    if "i18n" not in envelope or not isinstance(envelope["i18n"], dict):
        envelope["i18n"] = {"lang": lang}
    else:
        envelope["i18n"]["lang"] = lang
    return envelope


def i18n_after_request(response: Response) -> Response:
    try:
        ct = (response.mimetype or "").lower()
        if "application/json" not in ct:
            return response
        raw = response.get_data(as_text=True)
        if not raw:
            return response
        payload: Optional[Dict[str, Any]] = json.loads(raw)
        if not isinstance(payload, dict):
            return response
        lang = getattr(g, "lang", None) or _pick_lang()
        payload = _inject_i18n(payload, lang)
        response.set_data(json.dumps(payload, ensure_ascii=False))
        # keep content-length consistent if set
        if "Content-Length" in response.headers:
            response.headers["Content-Length"] = str(len(response.get_data()))
        return response
    except Exception:
        return response


def get_current_lang() -> str:
    return getattr(g, "lang", None) or "ko"
