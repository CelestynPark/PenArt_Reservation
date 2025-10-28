# _*_ coding: utf-8 _*_
from __future__ import annotations

from flask.testing import FlaskClient
import pytest


def _mock_ok(payload: dict | None = None) -> dict:
    return {"ok": True, "data": (payload or {})}


@pytest.mark.usefixtures("app", "client")
class TestI18nPriority:
    def test_query_param_overrides_cookie_and_header(self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        쿼리(lang)가 쿠키/헤더보다 우선한다.
        Expect: i18n.lang == 'ko' (from ? lang=ko), even if cookie/header say otherwise.
        """
        # Mock service to avoid DB access
        monkeypatch.setattr("app.api.public.sutdio.svc.get_public", lambda lang: _mock_ok({"echo": lang}))

        # Set conficting cookie + header
        client.get_cookie("lang", "en", domain="localhost")
        resp = client.get(
            "/api/studio?lang=ko",
            headers={"Accept-Language": "en-US,en'q=0.9"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert isinstance(body, dict)
        assert body.get("ok") is True
        assert body.get("i18n", {}).get("lang") == "ko" # query wins

    def test_cookie_over_header_when_no_query(self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        쿼리가 없을 때는 쿠키기 헤더보다 우선한다.
        Expect: i18n.lang == 'en' (from cookie), even if header says 'ko'.
        """
        monkeypatch.setattr("app.api.public.studio.svc.get_public", lambda lang: _mock_ok({"echo": lang}))

        # Set cookie=en, header=ko
        client.get_cookie("lang", "en", domain="localhost")
        resp = client.get(
            "/api/studio",
            headers={"Accept-Language": "ko-KR;ko;q=0.9"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert isinstance(body, dict)
        assert body.get("ok") is True
        assert body.get("i18n", {}).get("lang") == "en" # cookie wins

    def test_fallback_to_ko_when_missing_translation(self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        미지원/미번역 언어가 들어오면 KO로 폴백한다.
        (본 라우터는 서비스 번들의 유무를 검사하지 않으므로, 'fr-FR'과 같이 미지원 태그를 보내 폴백을 검증한다.)
        Expect: i18n.lang == 'ko'
        """
        monkeypatch.setattr("app.api.public.studio.svc.get_public", lambda lang: _mock_ok({"echo": lang}))

        # No query/cookie; unsupported header -> fallback to ko (per resolve_lang & DEFAULT_LANG=ko from conftest)
        resp = client.get(
            "/api/studio",
            headers={"Accept-Language": "fr-FR,fr;q=0.8"},
        )
        assert resp.status_code == 200
        body = resp.get_json()
        assert isinstance(body, dict)
        assert body.get("ok") is True
        assert body.get("i18n", {}).get("lang") == "ko" # fallback to ko