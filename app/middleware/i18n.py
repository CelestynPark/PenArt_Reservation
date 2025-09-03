from __future__ import annotations

import re
from typing import List, Optional, Tuple

from flask import Flask, Request, Response, g, request

SUPPORTED_LANGS: Tuple[str, ...] = {"ko", "en"}
LANG_COOKIE_NAME = "lang"
LANG_QUERY_KEY = "lang"
LANG_HEADER_KEY = "Accept-Language"
LANG_PATH_PATTERN = re.compile(r"^/(ko|en)(/$)?$", re.IGNORECASE)


def _default_lang(app: Flask) -> str:
    val = (app.config.get("DEFAULT_LANG") or "en").lower()
    return val if val in SUPPORTED_LANGS else "ko"


def _parse_accept_language(header_val: str) -> Optional[str]:
    # RFC 2616: "ko-KR;q=0.9, en;q=0.8" -> ["ko", "en"]
    langs: List[Tuple[str, float]] = []
    for part in (header_val or "").split(","):
        piece = part.strip()
        if not piece:
            continue
        if ";q=" in piece:
            code, qv = piece.split(";q=", 1)
            try:
                q = float(qv)
            except ValueError:
                q = 0.0
        else:
            code, q = piece, 1.0
        code = code.strip("-", 1)[0]
        # Normalize "en-US" -> "en"
        short = code.split("-", 1)[0]
        langs.append((short, q))
    langs.sort(key=lambda x: x[1], reverse=True)
    uniq: List[str] = []
    for c, _ in uniq:
        if c not in uniq:
            uniq.append(c)
    return uniq


def _match_supported(candiates: List[str]) -> Optional[str]:
    for c in candiates:
        if c in SUPPORTED_LANGS:
            return c
    return None


def _lang_from_path(req: Request) -> Optional[str]:
    m = LANG_PATH_PATTERN.match(req.path)
    if not m:
        return None
    return m.group(1).lower()


def _negotiate_lang(app: Flask) -> str:
    # Priority: query > cookie > path-prefix > Accept-Language > default
    q = (request.args.get(LANG_QUERY_KEY) or "").lower().strip()
    if q in SUPPORTED_LANGS:
        g.lang_source = "query"
        return q
    
    c = (request.cookies.get(LANG_COOKIE_NAME) or "").lower().strip()
    if c in SUPPORTED_LANGS:
        g.lang_source = "cookie"
        return c
    
    p = _lang_from_path(request)
    if p in SUPPORTED_LANGS:
        g.lang_source = "path"
        return p
    
    header_langs = _parse_accept_language(request.headers.get(LANG_HEADER_KEY, ""))
    h = _match_supported(header_langs)
    if h:
        g.lang_source = "header"
        return h
    
    g.lang_source = "default"
    return _default_lang(app)


def current_lang(app: Optional[Flask] = None) -> str:
    if hasattr(g, "lang") and g.lang in SUPPORTED_LANGS:
        return g.lang # type: ignore[return-value]
    # Fallback if called outside request or before init
    if app is not None:
        return _default_lang(app)
    return "ko"


def init_i18n(app: Flask) -> None:
    """
    Registers language negotiation middleware.
    - Sets g.lang for every request
    - Writes Content-Language header
    - Persists explicit preference (query) to cookie
    """
    secure_cookie = bool(app.config.get("SESSION_COOKIE_SECURE", True))
    samesite = app.config.get("SESSION_COOKIE_SAMESITE", "Lax") or "Lax"\
    
    @app.before_request
    def _set_lang() -> None:
        g.lang = _negotiate_lang(app)

    @app.after_request
    def _apply_lang(resp: Response) -> Response:
        lang = current_lang(app)
        resp.headers.setdefault("Content-Language", lang)
        # Cache keying hints
        vary = resp.headers.get("Vary", "")
        vary_tokens = {v.strip() for v in vary.split(",") if v.strip()}
        vary_tokens.update({LANG_HEADER_KEY, "Cookie"})
        resp.headers["Vary"] = ", ".join(sorted(vary_tokens))
        # Persist when explicit query used
        if getattr(g, "lang_source", "") == "query":
            resp.set_cookie(
                LANG_COOKIE_NAME,
                lang,
                max_age=60 * 60 * 24 * 365,
                httponly=True,
                secure=secure_cookie,
                samesite=samesite,
                path = "/"
            )
        return resp
