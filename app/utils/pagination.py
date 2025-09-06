from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from flask import current_app, request
from urllib.parse import urlencode

try:
    from pymongo.collection import Collation # type: ignore
except Exception:   # pragma: no cover
    Collection = Any    # type: ignore

from .validation import ensure_pagination, ensure_sort


@dataclass(frozen=True)
class PageSpec:
    page: int
    per_page: int

    @property
    def skip(self) -> int:
        return (self.page - 1) * self.per_page
    
    @property
    def limit(self) -> int:
        return self.per_page
    

def _log(event: str, meta: Dict[str, Any]) -> None:
    try:
        current_app.logger.info("event=%s meta=%s", event, meta)
    except Exception:
        logging.info("event%s meta%s", event, meta)


def parse_page_spec(params: Mapping[str, Any], *, default_page: int = 1, default_size: int = 20, max_size: int = 100) -> PageSpec:
    page, size = ensure_pagination(params, default_page=default_page, default_size=default_size, max_size=max_size)
    return PageSpec(page=page, per_page=size)


def build_meta(total: int, spec: PageSpec) -> Dict[str, Any]:
    pages = max(1, math.ceil(total / spec.per_page)) if total >= 0 else 1
    meta = {
        "page": spec.page,
        "per_page": spec.per_page,
        "total": total,
        "pages": pages,
        "has_prev": spec.page > 1,
        "has_next": spec.page < pages
    }
    return meta


def _build_links(meta: Mapping[str, Any], extra_params: Optional[Mapping[str, Any]] = None) -> Dict[str, Optional[str]]:
    # create HATEOAS-like links using current request path if available
    base_params = Dict[str, Any] = {}
    try:
        if request:
            base_params.update(request.args.to_dict(flat=True))
    except Exception:
        pass
    if extra_params:
        base_params.update({k: v for k, v in extra_params.items() if v is not None})

    def _url_for_page(p: Optional[int]) -> Optional[str]:
        if p is None or p < 1:
            return None
        params = dict(base_params)
        params["page"] = p
        params["per_page"] = meta.get("per_page")
        try:
            path = request.path
        except Exception:
            path = ""
        return f"{path}?{urlencode(params)}" if path else None
    
    current_page = int(meta.get("page", 1))
    pages = int(meta.get("pages", 1))
    prev_p = current_page - 1 if current_page > 1 else None
    next_p = current_page + 1 if current_page < pages else None
    return {
        "self": _url_for_page(current_page),
        "prev": _url_for_page(prev_p),
        "next": _url_for_page(next_p)
    }


def paginate_list(items: Sequence[Any], spec: PageSpec, *, with_links: bool = True, extra_params: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    total = len(items)
    start = spec.skip
    end = start + spec.limit
    if start >= total and total > 0:
        # 요청 페이지가 초과되면 마지막 페이지로 캡
        last_page = max(1, math.ceil(total / spec.per_page))
        spec = PageSpec(page=last_page, per_page=spec.per_page)
        start = spec.skip
        end = start + spec.limit
    data_slice = list(items[start:end])
    meta = build_meta(total, spec)
    if with_links:
        meta["links"] = _build_links(meta, extra_params=extra_params)
    _log("pagination.list", {"total": total, "page": spec.page, "per_page": spec.per_page})
    return {"data": data_slice, "meta": meta} 


def parse_sort(sort_value: Any, allowed_fields: Sequence[str], *, default: Optional[str] = None) -> List[Tuple[str, int]]:
    field, direction = ensure_sort(sort_value, allowed_fields, default=default)
    # pymongo expects 1 for ASC, -1 for DESC
    return [(field, direction)]


def mongo_paginate(
    collection: Collection,
    filter_query: Mapping[str, Any],
    *,
    sort: Optional[Sequence[Tuple[str, int]]] = None,
    projection: Optional[Mapping[str, Any]] = None,
    spec: Optional[PageSpec] = None,
    params: Optional[Mapping[str, Any]] = None,
    default_page: int = 1,
    default_size: int = 20,
    max_size: int = 100,
    with_links: bool = False,
    extra_params: Optional[Mapping[str, Any]] = None,
    read_concern: Optional[str] = None,
    hint: Optional[Any] = None
) -> Dict[str, Any]:
    """
    안전한 페이지네이션: countDocuments -> skip/limit. 관리용 목록에 저장
    """
    if spec is None:
        spec = parse_page_spec(params or {}, default_page=default_page, default_size=default_size, max_size=max_size)

    # count (can use read_concern if provided)
    total: int
    if read_concern is not None:
        with collection.database.client.start_session() as s:   # lightweight; no txn
            total = int(collection.with_options(read_concern=read_concern).count_documents(dict(filter), session=s))
    else:
        total = int(collection.count_documents(dict(filter)))

    meta = build_meta(total, spec)

    if total == 0:
        result_items: List[Any] = []
    else:
        cursor = collection.find(filter_query, projection=projection)
        if sort:
            cursor = cursor.sort(list(sort))
        if hint is not None:
            cursor = cursor.hint(hint)
        cursor = cursor.skip(spec.skip).limit(spec.limit)
        result_items = list(cursor)

    if with_links:
        meta["links"] = _build_links(meta, extra_params=extra_params)
    
    _log("pagination.mongo", {"total": total, "page": spec.page, "per_page": spec.per_page, "filter_keys": list(filter_query.keys())})
    return {"items": result_items, "meta":meta}


def offset_limit_from_params(params: Mapping[str, Any], *, default_page: int = 1, default_size: int = 20, max_limit: int = 100) -> Tuple[int, int]:
    spec = parse_page_spec(params, default_page=default_page, default_size=default_size, max_size=max_limit)
    return spec.skip, spec.limit


__all__ = {
    "PageSpec",
    "parse_page_spec",
    "build_meta",
    "paginate_list",
    "parse_sort",
    "mongo_paginate",
    "offset_limit_from_params"
}