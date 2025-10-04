from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import load_config
from app.core.constants import ErrorCode
from app.models import job_locks
from app.services import booking_service, metrics_service
from app.utils.time import isoformat_utc


__all__ = ["run_job_auto_complete"]


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return{"ok": True, "data": data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _hour_anchor(dt: datetime) -> datetime:
    u = _as_utc(dt)
    return datetime(u.year, u.month, u.day, u.hour, tzinfo=timezone.utc)


def _lock_key(now_utc: datetime) -> str:
    return "job:auto_complete:" + _hour_anchor(now_utc).strftime("%Y-%m-%dT%H")


def _list_candidates(now_iso: str, after_min: int) -> List[Dict[str, Any]]:
    from app.repositories import booking as booking_repo
    try:
        # 계약: end_at <= (now - after_min) 이고 status == confirmed 인 예약을 반환
        items: Optional[List[Dict[str, Any]]] = booking_repo.find_ready_to_complete(now_iso, int(after_min))
        return list(items or [])
    except booking_repo.RepoError:
        return []
    

def _complete(booking_id: str) -> bool:
    try:
        res = booking_service.transition(
            booking_id,
            action="complete",
            meta={"by": {"system": "job_auto_complete"}, "reason": "auto_complete"}
        )
        return bool(res.get("ok"))
    except booking_service.ServiceError:
        return False
    

def run_job_auto_complete(now_utc: datetime) -> Dict[str, Any]:
    """
    종료 후 N분 경과한 confirmed 예약을 completed로 전환한다.
    락 키: job:auto_complete:{yyyy-mm-ddThh}
    """
    try:
        cfg = load_config()
        after_min = int(getattr(cfg, "auto_complete_after_min", 15) or 15)

        key = _lock_key(now_utc)
        owner = "job_auto_complete"
        if not job_locks.acquire_lock(key, owner, ttl_sec=50 * 60):
            return _ok({"completed": 0, "skipped": 0})
        
        now_iso = isoformat_utc(_as_utc(now_utc))
        candidates = _list_candidates(now_iso, after_min)

        completed = 0
        skipped = 0

        for b in candidates:
            bid = str(b.get("_id") or b.get("id") or "")
            if not bid:
                skipped += 1
                continue
            
            if _complete(bid):
                completed += 1
                try:
                    metrics_service.ingest(
                        {
                            "type": "bookings.completed",
                            "timestamp": now_iso,
                            "meta": {"booking_id": bid, "reason": "auto_complete"}
                        }
                    )
                except Exception:
                    pass
            else:
                skipped += 1
            
        job_locks.release_lock(key, owner)
        return _ok({"completed": int(completed), "skipped": int(skipped)})
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    