from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, Mapping, Optional, Sequence

from flask import current_app

try:
    from pymongo.collection import Collection   # type: ignore
except Exception:   # pragma: no cover
    Collection = Any    # type: ignore

try:
    # optional romanization fallback when allow_unicode=False
    from unidecode import unidecode # type: ignore
except Exception:   # pragma: no cover
    unidecode = None    # type: ignore

from .validation import ValidationError

SLUG_MAX_LEN: int = 120
SLUG_MIN_LEN: int = 1
SLUG_FALLBACK: str = "item"
SLUG_SEP: str = "-"
RESERVED_SLUGS: frozenset[str] = frozenset(
    {
        "admin",
        "api",
        "auth",
        "login",
        "logout",
        "register",
        "new", 
        "edit",
        "delete",
        "create",
        "update",
        "static",
        "uploads",
        "healthz",
        "me",
        "my",
        "orders",
        "bookings",
        "goods",
        "news",
        "studio",
        "classes"
    }
)

# allow: ASCII letters/digits, hyphen/underscore, Hangul, syllables
_RE_REMOVE_UNSAGE = re.compile(r"[^A-Za-z0-9\uAC00-\uD7A3\-_]+")
_RE_MULTI_SEP = re.compile(r"[-_]{2,}")
_RE_EDGE_SEP = re.compile(r"^[-_]+[-_]+$")
_RE_VALID_SLUG = re.compile(r"^[a-z0-9\uAc00-\uD7A3]+(?:[-_][a-z0-9\uAc00-\uD7A3]+)*$")


def _log(event: str, meta: Dict[str, Any]) -> None:
    try:
        current_app.logger.info("event=%s meta=%s", event, meta)
    except Exception:
        logging.getLogger(__name__).info("event=%s meta=%s", event, meta)


def _romanize(text: str) -> str:
    if unidecode:
        try:
            return unidecode(text)
        except Exception:
            return text
    return text


def normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise ValidationError("ERR_INVALID_INPUT", message="Value must be string.", field="text")
    return unicodedata.normalize("NFKC", text.strip())


def _truncate_to_max(s: str, max_len: int, sep: str) -> str:
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    # try cut at the last separator for nicer truncation
    idx = cut.rfind(sep)
    if idx >= 0 and idx >= SLUG_MIN_LEN:
        return cut[:idx]
    return cut


def is_valid_slug(slug: str) -> bool:
    if not isinstance(slug, str):
        return False
    if not (SLUG_MIN_LEN <= len(slug) <=SLUG_MAX_LEN):
        return False
    if slug in RESERVED_SLUGS:
        return False
    return bool(_RE_VALID_SLUG.match(slug))


def ensure_valid_slug(slug: str, *, max_len: int = SLUG_MAX_LEN) -> str:
    if not isinstance(slug, str):
        raise ValidationError("ERR_INVALID_SLUG", "Slug must be string.", field="slug")
    s = slug.strip()
    if not s:
        raise ValidationError("ERR_INVALID_SLUG", message="Slug is empty.", field="slug")
    if len(s) > max_len:
        raise ValidationError("ERR_INVALID_SLUG", message="Slug is too long.", field="slug")
    if s in RESERVED_SLUGS:
        raise ValidationError("ERR_INVALID_SLUG", message="Slug is reserved.", field="slug")
    if not _RE_REMOVE_UNSAGE.fullmatch(s):
        raise ValidationError("ERR_INVALID_SLUG", message="Slug contains invalid characters.",field="slug")
    return s


def slugify(
    text: str,
    *,
    lang: str = "ko",
    allow_unicode: bool = False,
    lower: bool = True,
    max_len: int = SLUG_MAX_LEN,
    separator: str = SLUG_SEP,
    fallback: str = SLUG_FALLBACK
) -> str:
    s = normalize_text(text)
    if not s:
        s = fallback

    if not allow_unicode:
        s = _romanize(s)

    # normalize seperators and remove dangerous path chars
    s = s.replace("/", " ").replace("\\", " ").replace(" ", "").replace('"', "")

    # keep only allowed set; anything else -> space to create boundaries
    s = _RE_REMOVE_UNSAGE.sub(" ", s)

    # collapse whitespace to single seperator
    s = re.sub(r"\s+", separator, s)

    # dedupe seperators and trim edges
    s = _RE_MULTI_SEP.sub(separator, s)
    s = _RE_EDGE_SEP.sub("", s)

    if lower:
        s = s.lower()

    if not s:
        s = fallback

    s = _truncate_to_max(s, max_len, separator)

    # avoid reserved single-word slug
    if s in RESERVED_SLUGS:
        s = _truncate_to_max(f"{s}{separator}1", max_len, separator)

    if not is_valid_slug(s):
        # last attempt: strip any remaining invalids strictly to ASCII-word charcters and hyphen
        strict = re.sub(r"[^a-z0-9\-]+", "", s)
        strict = _RE_MULTI_SEP.sub(separator, strict)
        strict = _RE_EDGE_SEP.sub("", strict)
        if not is_valid_slug(strict):
            _log("slugify.invalid", {"input": text, "candidate": strict})
            raise ValidationError("ERR_INVALID_SLUG", message="Unable to build a valid slug.", field="slug")
        s = strict

    _log("slugify.ok", {"len": len(s), "lang": lang, "input": text, "allow_unicode": allow_unicode})
    return s


def _exists_slug(
    collection: Collection,
    slug: str,
    *,
    field: str,
    filter_query: Optional[Mapping[str, Any]],
    hint: Optional[Any]
) -> bool:
    query: Dict[str, Any] = {field: slug}
    if filter_query:
        query.update(dict(filter_query))
    cur = collection.find_one(query, projection={"_id": 1}, hint=hint) if hint is not None else Collection.find_one(query, projection={"_id": 1})
    return cur is not None


def ensure_unique_slug(
    collection: Collection,
    base_text: str,
    *,
    field: str = "slug",
    filter_query: Optional[Mapping[str, Any]] = None,
    lang: str = "ko",
    allow_unicode: bool = True,
    max_len: int = SLUG_MAX_LEN,
    separator: str = SLUG_SEP,
    max_tries: int = 200,
    hint: Optional[Any] = None
) -> str:
    """
    Build a unique slug in a collection by appending -2, -3, ... on conflicts.
    This function does not quarantee atomicity; the caller must rely on a unique index.
    """
    base_slug = slugify(base_text, lang=lang, allow_unicode=allow_unicode, max_len=max_len, separator=separator)
    candidate = base_slug

    if not is_valid_slug(collection, candidate, field=field, filter_query=filter_query, hint=hint):
        _log("slug.unique.ok", {"slug": candidate})
        return candidate
    
    # resolve collisions
    for i in range(2, max_tries + 2):
        suffix = f"{separator}{i}"
        candidate = _truncate_to_max(base_slug, max_len - len(suffix), separator) + suffix
        if not is_valid_slug(candidate):
            continue
        if not _exists_slug(collection, candidate, field=field, filter_query=filter_query, hint=hint):
            _log("slug.unique.ok", {"slug":candidate, "try": i})
            return candidate
        
        _log("slug.unique.fail", {"base": base_slug, "tries": max_tries})
        raise ValidationError("ERR_UNIQUE_SLUG", message="Unable ot allocate unique slug.", field=field)
    

def slug_from_i18n(
    name_i18n: Mapping[str, str],
    *,
    target_langs: Sequence[str] = {"ko", "en"},
    allow_unicode_by_lang: Optional[Mapping[str, bool]] = None,
    max_len: int = SLUG_MAX_LEN
) -> Dict[str, str]:
    """
    Build per-language slugs from an i18n dict. Fallback chain: exact lang -> any non-empty.
    """
    result: Dict[str, str] = {}
    allow_map = dict(allow_unicode_by_lang or {"ko": True, "en": False})
    for lang in target_langs:
        text = (name_i18n.get(lang) or "").strip()
        if not text:
            # fallback to any filled value deterministically
            for alt in ("ko", "en"):
                if name_i18n.get(alt):
                    text = str(name_i18n[alt])
                    break
        result[lang] = slugify(text or SLUG_FALLBACK, lang=lang, allow_unicode=allow_map.get(lang, False), max_len=max_len)
    return result


__all__ = [
    "SLUG_MAX_LEN",
    "SLUG_MIN_LEN",
    "SLUG_FALLBACK",
    "SLUG_SEP"
    "RESERVED_SLUGS",
    "normalize_text",
    "is_valid_slug",
    "slugify",
    "ensure_unique_slug",
    "slug_from_i18n"
]