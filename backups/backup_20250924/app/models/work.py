from __future__ import annotations

from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.collection import Collection
from pymongo.database import Database

from app.core.constants import SUPPORTED_LANGS
from app.models.base import BaseModel

COLLECTION = "works"
AUTHOR_TYPE = {"artist", "student"}

__all__ = ["COLLECTION", "get_collection", "ensure_indexes", "Work"]


def get_collection(db: Database) -> Collection:
    return db[COLLECTION]


def ensure_indexes(db: Database) -> None:
    col = get_collection(db)
    col.create_indexes(
        [
            IndexModel(
                [("author_type", ASCENDING), ("is_visible", ASCENDING), ("order", ASCENDING)],
                name="idx_author_visible_order"
            ),
            IndexModel([("order", ASCENDING), ("created_at", DESCENDING)], name="idx_order_created")
        ]
    )


def default_sort() -> list[tuple[str, int]]:
    return [("order", ASCENDING), ("created_at", DESCENDING)]


def _norm_str(v: Any, *, allow_empty: bool = False) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str):
        raise ValueError("invalid string")
    s = v.strip()
    if not allow_empty and s == "":
        raise ValueError("empty string not allowed")
    return s


def _norm_bool(v: Any, *, default: bool) -> bool:
    if v is None:
        return default
    return bool(v)


def _norm_int(v: Any, *, default: int = 0) -> int:
    if v is None or v == "":
        return default
    try:
        return int(v)
    except Exception:
        raise ValueError("invalid int")
    

def _norm_author_type(v: Any) -> str:
    s = _norm_str(v, allow_empty=False)
    if s not in AUTHOR_TYPE:
        raise ValueError("invalid author_type")
    return s


def _norm_i18n_map(v: Any, *, required_ko: bool = True, required: bool = True) -> dict[str, str]:
    if v is None:
        if required:
            raise ValueError("i18n required")
        return {}
    if not isinstance(v, dict):
        raise ValueError("i18n must be object")
    out: dict[str, str] = {}
    for k, val in v.items():
        if k not in SUPPORTED_LANGS:
            raise ValueError("unsupported languages")
        sv = _norm_str(val, allow_empty=False)
        out[k] = sv
    if required_ko and "ko" not in out:
        raise ValueError("ko required in i18n")
    if required and not out:
        raise ValueError("i18n required")
    return out


def _norm_images(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("images must be list")
    out: list[str] = []
    for img in v:
        if isinstance(img, str):
            url = _norm_str(img, allow_empty=False)
        elif isinstance(img, dict):
            url = _norm_str(img.get("url"), allow_empty=False)
        else:
            raise ValueError("invalid image required")
        out.append(url) # type: ignore[arg-type]
    return out


def _norm_tags(v: Any) -> list[str]:
    if v is None:
        return []
    if not isinstance(v, list):
        raise ValueError("tags must be list")
    out: list[str] = []
    for t in v:
        s = _norm_str(t, allow_empty=False)
        out.append(s)   # type: ignore[arg-type]
    return out


class Work(BaseModel):
    def __init__(self, doc: Optional[dict[str, Any]] = None):
        super().__init__(doc or {})
    
    @staticmethod
    def prepare_new(payload: dict[str, Any]) -> dict[str, Any]:
        author_type = _norm_author_type(payload.get("author_type"))
        title_i18n = _norm_i18n_map(payload.get("title_i18n"), required_ko=True, required=True)
        description_i18n = _norm_i18n_map(payload.get("description_i18n"), required_ko=True, required=True)
        images = _norm_images(payload.get("images"))
        tags = _norm_tags(payload.get("tags"))
        is_visible = _norm_bool(payload.get("is_visible"), default=True)
        order = _norm_int(payload.get("order"), default= 0)

        doc: dict[str, Any] = {
            "author_type": author_type,
            "title_i18n": title_i18n,
            "description_i18n": description_i18n,
            "images": images,
            "tags": tags,
            "is_visible": is_visible,
            "order": order
        }
        return Work.stamp_new(doc)
    
    @staticmethod
    def prepare_update(partial: dict[str, Any]) -> dict[str, Any]:
        upd: dict[str, Any] = {}

        if "author_type" in partial:
            upd["author_type"] = _norm_author_type(partial.get("author_type"))

        if "title_i18n" in partial:
            upd["title_i18n"] = _norm_i18n_map(partial.get("title_i18n"), required_ko=True, required=True)

        if "description_i18n" in partial:
            upd["description_i18n"] = _norm_i18n_map(partial.get("description_i18n"), required_ko=True, required=True)

        if "images" in partial:
            upd["images"] = _norm_images(partial.get("images"))

        if "tags" in partial:
            upd["tags"] = _norm_tags(partial.get("tags"))

        if "is_visible" in partial:
            upd["is_visible"] = _norm_bool(partial.get("is_visible"), default=True)

        if "order" in partial:
            upd["order"] = _norm_int(partial.get("order"), default=0)
        
        return Work.stamp_new(upd)