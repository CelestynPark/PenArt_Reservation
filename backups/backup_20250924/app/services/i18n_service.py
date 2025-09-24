from __future__ import annotations

import json
import os
from threading import Lock
from typing import Any, Dict, Optional, Mapping, Iterable

from flask import Request
from app.core.constants import LANG_KO, LANG_EN, SUPPORTED_LANGS, ErrorCode


class I18nFormatError(Exception):
    code = ErrorCode.INVALID_PAYLOAD

    def __init__(self, key: str, missing_key: str):
        super().__init__(f"Missing format key '{missing_key}' for i18n key '{key}'")
        self.key = key
        self.missing_key = missing_key


class I18nService:
    def __init__(self, bundle_paths: Optional[Mapping[str, str]] = None):
        self._bundle_paths: Dict[str, str] = dict(
            bundle_paths
            or {
                LANG_KO: os.path.join("app", "i18n", "ko.json"),
                LANG_EN: os.path.join("app", "i18n", "en.json"),
            }
        )
        self._bundles: Dict[str, Dict[str, Any]] = {LANG_KO: {}, LANG_EN: {}}
        self._lock = Lock()
        self._loaded = False
        self._load_once()

    def _load_once(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            for lang in SUPPORTED_LANGS:
                path = self._bundle_paths.get(lang)
                if not path:
                    self._bundles[lang] = {}
                    continue
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self._bundles[lang] = data if isinstance(data, dict) else {}
                except FileNotFoundError:
                    self._bundles[lang] = {}
            self._loaded = True

    @staticmethod
    def _norm_lang(lang: Optional[str]) -> str:
        l = (lang or "").split(",")[0].strip().lower()
        if not l:
            return LANG_KO
        for s in SUPPORTED_LANGS:
            if l == s or l.startswith(s + "-"):
                return s
        return LANG_KO

    @staticmethod
    def _iter_accept(lang_header: str) -> Iterable[str]:
        for part in lang_header.split(","):
            base = part.split(";")[0].strip().lower()
            if base:
                yield base

    def detect_lang(self, request: Request) -> str:
        q = request.args.get("lang")
        if q:
            return self._norm_lang(q)
        c = request.cookies.get("lang")
        if c:
            return self._norm_lang(c)
        h = request.headers.get("Accept-Language", "")
        for cand in self._iter_accept(h):
            norm = self._norm_lang(cand)
            if norm in SUPPORTED_LANGS:
                return norm
        return LANG_KO

    def _lookup(self, lang: str, key: str) -> Any:
        v = self._bundles.get(lang, {}).get(key)
        if v is None and lang != LANG_KO:
            v = self._bundles.get(LANG_KO, {}).get(key)
        return v if v is not None else key

    def get(self, lang: str, key: str, **kwargs: Any) -> str:
        self._load_once()
        l = self._norm_lang(lang)
        raw = self._lookup(l, key)
        s = str(raw)
        if ("{" in s and "}" in s) or kwargs:
            try:
                return s.format(**kwargs)
            except KeyError as e:
                missing = str(e).strip("'")
                raise I18nFormatError(key, missing)
        return s


# Singleton + functional helper
i18n = I18nService()


def detect_lang(request: Request) -> str:
    return i18n.detect_lang(request)
