from __future__ import annotations

import re
from typing import Mapping, Optional, Sequence, Tuple

from app.core.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


__all__ = (
    "ValidationError",
    "require",
    "one_of",
    "is_email",
    "is_phone_kr",
    "validate_pagination",
)


class ValidationError(ValueError):
    pass


_RE_EMAIL = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

# KR phone (mobile/landline), local or +82, separators -, space, or dot
_RE_MOBILE_LOCAL = re.compile(r"^01[016789][\-\.\s]?\d{3,4}[\-\.\s]?\d{4}$")
_RE_MOBILE_INTL = re.compile(r"^\+82[\-\.\s]?0?1[016789][\-\.\s]?\d{3,4}[\-\.\s]?\d{4}$")
_RE_LAND_LOCAL = re.compile(r"^0\d{1,2}[\-\.\s]?\d{3,4}[\-\.\s]?\d{4}$")
_RE_LAND_INTL = re.compile(r"^\+82[\-\.\s]?0?\d{1,2}[\-\.\s]?\d{3,4}[\-\.\s]?\d{4}$")

# sort: field:asc|desc (letters, digits, underscore, dot)
_RE_SORT = re.compile(r"^(?P<field>[A-Za-z0-9_.]+):(?P<dir>asc|desc)$", re.IGNORECASE)


def _get(obj: Mapping, key: str):
    if obj is None:
        return None
    try:
        return obj[key]
    except Exception:
        return None


def require(obj: Mapping, *keys: str) -> None:
    if obj is None:
        raise ValidationError("payload required")
    for k in keys:
        if k not in obj:
            raise ValidationError(f"missing field: {k}")
        v = _get(obj, k)
        if v is None:
            raise ValidationError(f"null field: {k}")
        if isinstance(v, str) and v.strip() == "":
            raise ValidationError(f"empty field: {k}")


def one_of(obj: Mapping, key: str, values: Sequence) -> None:
    if key not in obj:
        raise ValidationError(f"missing field: {key}")
    v = _get(obj, key)
    if v is None:
        raise ValidationError(f"null field: {key}")
    if v not in values:
        raise ValidationError(f"invalid value for {key}")


def is_email(s: str) -> bool:
    if not isinstance(s, str):
        return False
    return bool(_RE_EMAIL.match(s.strip()))


def is_phone_kr(s: str) -> bool:
    if not isinstance(s, str):
        return False
    x = s.strip()
    return bool(
        _RE_MOBILE_LOCAL.match(x)
        or _RE_MOBILE_INTL.match(x)
        or _RE_LAND_LOCAL.match(x)
        or _RE_LAND_INTL.match(x)
    )


def validate_pagination(q: Mapping) -> Tuple[int, int, Optional[str]]:
    page = 1
    size = DEFAULT_PAGE_SIZE
    sort: Optional[str] = None

    raw_page = _get(q, "page")
    raw_size = _get(q, "size")
    raw_sort = _get(q, "sort")

    try:
        if raw_page is not None:
            page = int(raw_page)
    except Exception:
        page = 1
    if page < 1:
        page = 1

    try:
        if raw_size is not None:
            size = int(raw_size)
    except Exception:
        size = DEFAULT_PAGE_SIZE
    if size < 1:
        size = DEFAULT_PAGE_SIZE
    if size > MAX_PAGE_SIZE:
        size = MAX_PAGE_SIZE

    if isinstance(raw_sort, str):
        m = _RE_SORT.match(raw_sort.strip())
        if m:
            field = m.group("field")
            # guard: no leading '$' or double dots
            if not field.startswith("$") and ".." not in field:
                direction = m.group("dir").lower()
                sort = f"{field}:{direction}"

    return page, size, sort
