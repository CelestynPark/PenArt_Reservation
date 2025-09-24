from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

__all__ = [
    "ValidationError",
    "require_fields",
    "validate_pagination",
    "validate_enum",
]

PAGE_DEFAULT = 20
PAGE_MAX = 100
_SORT_DIR_ALLOWED = {"asc", "desc"}


@dataclass(eq=False)
class ValidationError(Exception):
    message: str
    field: Optional[str] = None
    code: str = "ERR_INVALID_PAYLOAD"

    def __str__(self) -> str:
        if self.field:
            return f"{self.field}: {self.message}"
        return self.message


def _as_int(v: object, *, field: str, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        iv = int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError) as e:
        raise ValidationError("must be an integer", field) from e
    if minimum is not None and iv < minimum:
        raise ValidationError(f"must be >= {minimum}", field)
    if maximum is not None and iv > maximum:
        raise ValidationError(f"must be <= {maximum}", field)
    return iv


def _is_missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def require_fields(payload: Dict[str, object], fields: Sequence[str]) -> None:
    if not isinstance(payload, dict):
        raise ValidationError("payload must be an object")
    for f in fields:
        if f not in payload or _is_missing(payload.get(f)):
            raise ValidationError("is required", f)


def validate_enum(value: str, allowed: Iterable[str], field: str) -> None:
    if value not in set(allowed):
        raise ValidationError(f"must be one of {sorted(set(allowed))}", field)


def _parse_sort_item(item: str) -> Tuple[str, str]:
    item = item.strip()
    if not item:
        raise ValidationError("invalid sort segment")
    parts = item.split(":")
    field = parts[0].strip()
    direction = parts[1].strip().lower() if len(parts) > 1 else "asc"
    if direction not in _SORT_DIR_ALLOWED:
        raise ValidationError("sort direction must be 'asc' or 'desc'", "sort")
    if not field:
        raise ValidationError("sort field is empty", "sort")
    return field, direction


def validate_pagination(
    q: Dict[str, object],
    *,
    default_size: int = PAGE_DEFAULT,
    max_size: int = PAGE_MAX,
    allowed_sort_fields: Optional[Iterable[str]] = None,
) -> Tuple[int, int, List[Tuple[str, str]]]:
    page_raw = q.get("page", 1)
    size_raw = q.get("size", default_size)
    page = _as_int(page_raw, field="page", minimum=1)
    size = _as_int(size_raw, field="size", minimum=1, maximum=max_size)

    sort_list: List[Tuple[str, str]] = []
    sort_raw = q.get("sort")
    if sort_raw is not None:
        if not isinstance(sort_raw, str):
            raise ValidationError("sort must be a string like 'field:asc'", "sort")
        segments = [s for s in (x.strip() for x in sort_raw.split(",")) if s]
        if not segments:
            raise ValidationError("sort is empty", "sort")
        for seg in segments:
            field, direction = _parse_sort_item(seg)
            if allowed_sort_fields is not None:
                if field not in set(allowed_sort_fields):
                    raise ValidationError(f"unknown sort field '{field}'", "sort")
            sort_list.append((field, direction))
    return page, size, sort_list
