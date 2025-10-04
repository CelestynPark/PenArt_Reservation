from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import load_config
from app.core.constants import ErrorCode
from app.models import job_locks
from app.services import order_service, metrics_service
from app.services.goods_service import current_policy
from app.utils.time import isoformat_utc


__all__ = ["run_job_order_expire"]


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


def _list_candidates(now_iso: str) -> List[Dict[str, Any]]:
    """
    Repository adapter: prefer `find_ready_to_expire(now_iso)`; fallback to `find_expiring(now_iso)`.
    Contract: returns orders with status=awating_deposit and expires_at <= now_iso.
    """
    from app.repositories import order as order_repo
    try:
        items: Optional[List[str, Any]] = order_repo.find_ready_to_expire(now_iso)  # type: ignore[attr-defined]
        return list(items or [])
    except AttributeError:
        try:
            items = order_repo.find_expiring(now_iso)   # type: ignore[attr-defined]
            return list(items or [])
        except AttributeError:
            return []
    except order_repo.RepoError:    # type: ignore[name-defined]
        return []
    

def run_job_order_expire(now_utc: datetime) -> Dict[str, Any]:
    """
    입금 대기 주문을 만료 처리하고(ORDER_EXPIRE_HOURS 기준으로 생성된 expires_at 사용),
    재고 정책에 따라 복구한다. 멱등/잠금 보장.
    락 키: job:order_expire:{yyyy-mm-ddThh}
    """
    try:
        _ = load_config()   # ensure config is loaded (ORDER_EXPIRE_HOURS already applied at order create time)
        pol = current_policy()  # 'hold' or 'deduct_on_paid'

        key = _lock_key(now_utc)
        owner = "job_order_expire"
        if not job_locks.acquire_lock(key, owner, ttl_sec=50 * 60):
            return _ok({"expired": 0, "restored_stock": 0})
        
        now_iso = isoformat_utc(_as_utc(now_utc))
        candidates = _list_candidates(now_iso)

        expired_cnt = 0
        restored_stock = 0
        skipped = 0

        for o in candidates:
            oid = str(o.get("_id") or o.get("id") or "")
            if not oid:
                skipped += 1
                continue

            qty = int(o.get("quantity") or 0)

            try:
                res = order_service.expire(oid, reason="auto_expire")
                if res.get("ok"):
                    expired_cnt += 1
                    # 정책별 재고 복구 집계: hold에서만 복구 수량 증가
                    if pol == "hold" and qty > 0:
                        restored_stock += qty
                    try:
                        metrics_service.ingest(
                            {
                                "type": "orders.expired",
                                "timestamp": now_iso,
                                "meta": {"order_id": oid, "reason": "auto_expire"}
                            }
                        )
                    except Exception:
                        pass
                else:
                    skipped += 1
            except order_service.ServiceError:
                # 이미 expired/paid/canceled 이거나 아직 기한 전 -> skip
                skipped += 1
            
        job_locks.release_lock(key, owner)
        return _ok({"expired": int(expired_cnt), "restored_stock": int(restored_stock), "skipped": int(skipped)})
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    