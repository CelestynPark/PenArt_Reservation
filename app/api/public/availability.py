from __future__ import annotations

from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from app.core.constants import (
    API_DATA_KEY,
    API_ERROR_KEY,
    API_I18N_KEY,
    API_OK_KEY,
    ErrorCode
)
from app.services.i18n_service import resolve_lang
from app.services import availability_service as avail_svc
from app.utils.time import parse_kst_date

bp = Blueprint("availability_public", __name__, url_prefix="/api")


def _with_lang(envelope: Dict[str, Any], lang: str) -> Dict[str, Any]:
    envelope[API_I18N_KEY] = {"lang": lang}
    return envelope


@bp.get("/availability")
def get_availability():
    """
    GET /api/availability?date=YYYY-MM-DD&service_id?
    - date is interpreted as a KST local calendar day.
    - Server converts to the UTC window and delegates to availability service.
    Response:
        { ok: true, data: { date_kst, slots: [{service_id, start_at, end_at}]} }, i18n:{lang} }
    Times in response are UTC ISO8601 (Z).
    """
    lang = resolve_lang(request.args.get("lang"), request.cookies.get("lang"), request.headers.get("Accept-Language"))
    date_kst = request.args.get("date",type=str)
    service_id = request.args.get("service_id", type=str)

    try:
        if not isinstance(date_kst, str) or len(date_kst) != 10:
            raise ValueError("date must be 'YYYY-MM-DD' in KST")
        
        # Validate/convert once to enforce spec (window is derived here; service composes slots)
        # We don't use the returned values directly; this guards format & KST->UTC logic.
        _start_utc, _end_utc = parse_kst_date(date_kst)

        raw_slots: List[Dict[str, Any]] = avail_svc.get_slots_for_date_kst(date_kst, service_id=service_id)
        slots: List[Dict[str, Any]] = [
            {
                "service_id": service_id if service_id else None,
                "start_at": s.get("start_at"),
                "end_at": s.get("end_at")
            }
            for s in raw_slots
            if isinstance(s, dict) and "start_at" in s and "end_at" in s
        ]

        body = _with_lang(
            {
                API_OK_KEY: True,
                API_DATA_KEY: {"date_kst": date_kst, "slots": slots}
            },
            lang
        )
        return jsonify(body)

    except ValueError as ve:
        body = _with_lang(
            {
                API_OK_KEY: False,
                API_ERROR_KEY: {"code": ErrorCode.ERR_INVALID_PAYLOAD.value, "message": str(ve)}
            },
            lang
        )
        return jsonify(body), 400
    except Exception:
        body = _with_lang(
            {
                API_OK_KEY: False, 
                API_ERROR_KEY: {"code": ErrorCode.ERR_INTERNAL.value, "message": "internal error"},
            },
            lang
        )
        return jsonify(body), 500
    