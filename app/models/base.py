from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Dict, Mapping, MutableMapping

from app.utils.time import now_utc, isoformat_utc

__all__ = [
    "TIMESTAMP_FIELDS",
    "utc_now",
    "stamp_for_insert",
    "stamp_for_update",
]


TIMESTAMP_FIELDS = ("created_at", "updated_at")


class ModelPayloadError(ValueError):
    code = "ERR_INVALID_PAYLOAD"


def utc_now() -> datetime:
    return now_utc()


def _ensure_mapping(doc: Mapping) -> None:
    if not isinstance(doc, Mapping):
        raise ModelPayloadError("document must be a mapping/dict")


def _stamp_iso_now() -> str:
    return isoformat_utc(utc_now())


def stamp_for_insert(doc: Mapping) -> Dict:
    _ensure_mapping(doc)
    out: MutableMapping = deepcopy(dict(doc))
    ts = _stamp_iso_now()
    out["created_at"] = ts
    out["updated_at"] = ts
    return dict(out)


def stamp_for_update(doc: Mapping) -> Dict:
    _ensure_mapping(doc)
    out: MutableMapping = deepcopy(dict(doc))
    out.pop("created_at", None)
    out["updated_at"] = _stamp_iso_now()
    return dict(out)
