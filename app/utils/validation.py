from __future__ import annotations

import re
from typing import Any, Iterable

from bson import ObjectId
from werkzeug.datastructures import FileStorage

from app.core.constants import PAGE_DEFAULT, SIZE_DEFAULT, SIZE_MAX


def validate_pagination(page: Any, size: Any) -> tuple[int, int]:
    def _to_int(v: Any, default: int) -> int:
        if v is None or v == "":
            return default
        try:
            return int(v)
        except Exception as e:  # noqa: BLE001
            raise ValueError("invalid pagination parameter") from e

    p = _to_int(page, PAGE_DEFAULT)
    s = _to_int(size, SIZE_DEFAULT)
    if p < 1:
        raise ValueError("page must be >= 1")
    if s < 1 or s > SIZE_MAX:
        raise ValueError(f"size must be between 1 and {SIZE_MAX}")
    return p, s


def parse_sort(expr: str | None, allowed: Iterable[str]) -> list[tuple[str, int]]:
    if not expr:
        return []
    allowed_set = set(allowed)
    if not allowed_set:
        raise ValueError("no sortable fields defined")
    results: list[tuple[str, int]] = []
    parts = [p.strip() for p in expr.split(",") if p.strip()]
    for part in parts:
        if ":" not in part:
            raise ValueError("invalid sort format, expected field:asc|desc")
        field, direction = (x.strip() for x in part.split(":", 1))
        if field not in allowed_set:
            raise ValueError(f"unsupported sort field: {field}")
        if direction not in ("asc", "desc"):
            raise ValueError("sort direction must be 'asc' or 'desc'")
        results.append((field, 1 if direction == "asc" else -1))
    return results


def ensure_object_id(v: str) -> ObjectId:
    if not isinstance(v, str) or not ObjectId.is_valid(v):
        raise ValueError("invalid ObjectId")
    return ObjectId(v)


def ensure_enum(v: str, allowed: Iterable[str]) -> str:
    if not isinstance(v, str):
        raise ValueError("enum must be a string")
    vv = v.strip()
    allowed_set = set(allowed)
    if vv not in allowed_set:
        raise ValueError(f"invalid enum value: {vv}")
    return vv


# --- uploads ---
_IMG_EXTS = {"jpg", "jpeg", "png", "webp"}
_PDF_EXTS = {"pdf"}
_EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)
_PHONE_RETS = (
    re.compile(r"^010-\d{4}-\d{4}$"),        # domestic dashed
    re.compile(r"^\+82-10-\d{4}-\d{4}$"),    # intl dashed
    re.compile(r"^010\d{8}$"),               # compact domestic
    re.compile(r"^\+8210\d{8}$"),            # compact intl
)


def _ext_from_filename(name: str) -> str:
    if not isinstance(name, str) or "." not in name:
        return ""
    return name.rsplit(".", 1)[1].lower().lstrip(".")


def _expected_mime_for_ext(ext: str) -> set[str]:
    if ext in _IMG_EXTS:
        return {"image/jpeg", "image/png", "image/webp", "image/pjpeg"}
    if ext in _PDF_EXTS:
        return {"application/pdf"}
    return set()


def validate_upload(file: FileStorage, exts: set[str], max_mb: int) -> None:
    if not isinstance(file, FileStorage):
        raise ValueError("invalid file")
    if max_mb <= 0:
        raise ValueError("max size must be positive")

    ext = _ext_from_filename(file.filename or "")
    if not ext or ext not in {e.lower().lstrip(".") for e in exts}:
        raise ValueError("file extension not allowed")

    ctype = (file.mimetype or "").strip().lower()
    allowed_mimes = _expected_mime_for_ext(ext)
    if allowed_mimes and ctype not in allowed_mimes:
        raise ValueError("MIME type not allowed")

    size_bytes: int | None = getattr(file, "content_length", None)
    if size_bytes is None:
        try:
            pos = file.stream.tell()
            file.stream.seek(0, 2)
            size_bytes = file.stream.tell()
            file.stream.seek(pos)
        except Exception as e:  # noqa: BLE001
            raise ValueError("unable to determine file size") from e

    if size_bytes is None:
        raise ValueError("unable to determine file size")

    if size_bytes > max_mb * 1024 * 1024:
        raise ValueError("file too large")


def validate_phone_or_none(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    if not s:
        return None
    for r in _PHONE_RETS:
        if r.fullmatch(s):
            return s
    raise ValueError("invalid phone format")


def validate_email_or_none(v: str | None) -> str | None:
    if v is None:
        return None
    s = v.strip()
    if not s:
        return None
    if not _EMAIL_RE.fullmatch(s):
        raise ValueError("invalid email")
    return s
