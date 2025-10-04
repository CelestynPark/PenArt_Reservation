from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import load_config
from app.core.constants import ErrorCode
from app.models import job_locks
from app.services import booking_service, metrics_service
from app.utils.time import isoformat_utc


__all__ = ["run_job_stale_cleanup"]


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return{"ok": True, "data": data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _lock_key(now_utc: datetime) -> str:
    d = _as_utc(now_utc).strftime("%Y-%m-%d")
    return f"job:stale_cleanup:{d}"


def _list_candidates(now_iso: str) -> List[Dict[str, Any]]:
    """
    Repository 계약(선언): 'stale requested' 후보를 반환한다.
    - 상태: requested
    - 정책 기준에 따라 더 이상 대기 유지가 부적절한 건(예: 시작 임박/경과 등)
    구현 상세는 booking_repo 내부 규칙에 위임한다.
    """
    from app.repositories import booking as booking_repo    # 지연 임포트(순환 회피)

    try: 
        # find_stale_requested(now_iso) 계약을 사용한다.
        # (리포지토리에서 now_iso를 기준으로 정책/기간을 평가해 후보를 들려준다)
        items: Optional[List[Dict[str, Any]]] = booking_repo.find_stale_requested(now_iso)
        return list(items or [])
    except booking_repo.RepoError:
        return []
    

def _cancel(booking_id: str) -> bool:
    try:
        res = booking_service.transition(
            booking_id,
            action="cancel",
            meta={"by": {"system": "job_stale_cleanup"}, "reason": "stale_requested"}
        )
        return bool(res.get("ok"))
    except booking_service.ServiceError:
        return False
    

def run_job_stale_cleanup(now_utc: datetime) -> Dict[str, Any]:
    """
    오래된 requested 예약을 자동 취소한다.
    - 락 키: job:stale_cleanup:{yyyy-mm-dd}
    - 멱등: 이미 취소/변경된 건은 transition 단계에서 자연 skip
    - 결과: {ok:true,data:{canceled:int,kept:int}}
    """
    try:
        cfg = load_config() # 향후 정책 파라미터 확장 대비(미사용 허용)
        _ = cfg

        key = _lock_key(now_utc)
        owner = "job_stale_cleanup"
        # 하루 1회 실행 전제이나 중복 방지르 위해 TTL 50분으로 제한
        if not job_locks.acquire_lock(key, owner, ttl_sec=50 * 60):
            return _ok({"canceled": 0, "kept": 0})
        
        now_iso = isoformat_utc(_as_utc(now_utc))
        candidates = _list_candidates(now_iso)

        canceled = 0
        kept = 0

        for b in candidates:
            bid = str(b.get("_id") or b.get("id") or "")
            if not bid:
                kept += 1
                continue

            # 컷오프 등 정책은 서비스 레이어에서 재확인
            if _cancel(bid):
                canceled += 1
                try:
                    metrics_service.ingest(
                        {
                            "type": "bookings.canceled",
                            "timestamp": now_iso,
                            "meta": {"bookign_id": bid, "reason": "stale_requested"},
                        }
                    )
                except Exception:
                    pass
            else:
                kept += 1
            
        job_locks.release_lock(key, owner)
        return _ok({"canceled": int(canceled), "kept": int(kept)})
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    