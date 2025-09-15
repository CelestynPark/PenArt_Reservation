from __future__ import annotations

from datetime import timedelta
from typing import Optional

from flask import Flask, Request, Response, g, request

from app.config import get_settings
from app.services.i18n_service import detect_lang as _detect_lang

__all__ = ["init_i18n"]


COOKIE_NAME = "lang"
COOKIE_MAX_AGE = int(timedelta(days=365).total_seconds())  # 1 year


def _choose_lang(req: Request) -> str:
    return _detect_lang(req)


def init_i18n(app: Flask) -> None:
    settings = get_settings()

    @app.before_request  # type: ignore[misc]
    def _before_i18n() -> None:
        g.lang = _choose_lang(request)

    @app.after_request  # type: ignore[misc]
    def _after_i18n(response: Response) -> Response:
        lang: Optional[str] = getattr(g, "lang", None)
        if lang:
            response.headers.setdefault("Content-Language", lang)

        # Persist language selection only when explicitly requested via query
        if "lang" in request.args and lang:
            response.set_cookie(
                COOKIE_NAME,
                lang,
                max_age=COOKIE_MAX_AGE,
                secure=settings.is_production,
                httponly=False,  # readable by client for SSR/CSR toggles
                samesite="Lax",
                path="/",
            )
        return response
