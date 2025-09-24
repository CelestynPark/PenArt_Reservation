from __future__ import annotations

import threading
import time
from typing import Optional, Tuple

from flask import Request, current_app, g, request

from app.core.constants import ErrorCode
from app.utils.responses import fail


# ---------- In-memory fallback store (thread-safe) ----------
class _MemoryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Tuple[int, float]] = {}  # key -> (count, expire_epoch)

    def incr(self, key: str, ttl: int) -> int:
        now = time.time()
        with self._lock:
            count, exp = self._data.get(key, (0, 0))
            if exp <= now:
                count, exp = 0, now + ttl
            count += 1
            self._data[key] = (count, exp)
            return count

    def ttl(self, key: str) -> int:
        with self._lock:
            _, exp = self._data.get(key, (0, 0))
            rem = int(exp - time.time())
            return max(rem, -1) if exp else -1


_memory_store = _MemoryStore()


def _get_store():
    """
    Returns a Redis-like store if available (app.extensions.{redis|cache}),
    otherwise uses in-process memory store.
    """
    try:
        from app import extensions  # type: ignore
    except Exception:
        extensions = None  # type: ignore

    # Prefer Redis client if provided by extensions
    client = None
    if extensions is not None:
        client = getattr(extensions, "redis", None) or getattr(extensions, "cache", None)

    if client is None:
        return "memory", _memory_store
    return "redis", client


def _redis_incr_with_ttl(client, key: str, ttl: int) -> int:
    # Works with redis-py like clients
    pipe = client.pipeline() if hasattr(client, "pipeline") else None
    if pipe:
        pipe.incr(key)
        # Set expire only if not set
        if getattr(client, "ttl")(key) in (-2, -1):  # -2 no key, -1 no expire
            pipe.expire(key, ttl)
        else:
            # Ensure at least some TTL remains
            pass
        res = pipe.execute()
        return int(res[0])
    # Fallback naive (non-pipeline) path
    count = int(client.incr(key))
    try:
        if int(client.ttl(key)) in (-2, -1):
            client.expire(key, ttl)
    except Exception:
        client.expire(key, ttl)
    return count


def _redis_ttl(client, key: str) -> int:
    try:
        t = int(client.ttl(key))
        # Redis: -2 no key, -1 no expire
        if t < 0:
            return -1
        return t
    except Exception:
        return -1


# ---------- Public helpers ----------
def key_for(req: Request) -> str:
    """
    Compose a stable rate-limit identity key:
    - Primary: client IP (X-Forwarded-For first, else remote_addr)
    - Secondary: user id if available (g.user_id), else '-'
    """
    ip = (req.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or (req.remote_addr or "")
    uid = getattr(g, "user_id", None)
    return f"{ip}|{uid or '-'}"


# ---------- Middleware factory ----------
def rate_limit(per_min: Optional[int] = None):
    """
    Flask before_request middleware factory.

    Usage (in app factory):
        app.before_request(rate_limit())

    Config (optional):
        RATE_LIMIT_PER_MIN: int (default 60)
        RATE_LIMIT_WHITELIST: comma-separated IPs (default none)
        RATE_LIMIT_EXEMPT_PREFIXES: comma-separated path prefixes (default: /healthz,/readyz,/static,/favicon.ico)
    """
    def _before_request():
        # Exempt safe/infra routes
        cfg = current_app.config or {}
        default_exempt = ["/healthz", "/readyz", "/static", "/favicon.ico"]
        addl = str(cfg.get("RATE_LIMIT_EXEMPT_PREFIXES", "") or "").split(",") if cfg.get("RATE_LIMIT_EXEMPT_PREFIXES") else []
        exempt_prefixes = tuple(p.strip() for p in (default_exempt + addl) if p.strip())
        path = request.path or "/"
        if request.method == "OPTIONS" or any(path.startswith(p) for p in exempt_prefixes):
            return None

        # Whitelist by IP
        ip = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip() or (request.remote_addr or "")
        wl = str(cfg.get("RATE_LIMIT_WHITELIST", "") or "").split(",") if cfg.get("RATE_LIMIT_WHITELIST") else []
        if ip and ip in (x.strip() for x in wl if x.strip()):
            return None

        # Determine limit & window
        limit = int(per_min or cfg.get("RATE_LIMIT_PER_MIN", 60))
        if limit <= 0:
            return None  # disabled

        ident = key_for(request)
        epoch = int(time.time())
        window_sec = 60
        window_id = epoch // window_sec
        reset_at = (window_id + 1) * window_sec  # unix ts when the window resets
        ttl = reset_at - epoch + 1  # keep the bucket slightly longer than rest of window
        store_kind, store = _get_store()

        bucket_key = f"rl:{ident}:{window_id}"

        # Increment
        if store_kind == "redis":
            count = _redis_incr_with_ttl(store, bucket_key, ttl)
            rem_ttl = _redis_ttl(store, bucket_key)
        else:
            count = store.incr(bucket_key, ttl)
            rem_ttl = store.ttl(bucket_key)

        remaining = max(limit - count, 0)

        # Headers for clients
        retry_after = rem_ttl if remaining <= 0 else 0
        # If over the limit, return standardized 429 body
        if count > limit:
            resp = fail(
                code=ErrorCode.RATE_LIMIT,
                message="Too many requests",
                status=429,
            )
            try:
                resp.headers["Retry-After"] = str(max(retry_after, 1))
                resp.headers["X-RateLimit-Limit"] = str(limit)
                resp.headers["X-RateLimit-Remaining"] = "0"
                resp.headers["X-RateLimit-Reset"] = str(reset_at)
            except Exception:
                pass
            return resp

        # Attach informative headers on success paths as well
        try:
            # Note: these headers are advisory only
            request.access_control_expose_headers = True  # hint for CORS layers if present
            # Using Flask's after_request would be cleaner, but keep minimal & synchronous here.
            # Many reverse proxies will forward these through.
            current_app.logger  # touch to avoid unused warning under some linters
            request.rate_limit = {  # type: ignore
                "limit": limit,
                "remaining": remaining,
                "reset": reset_at,
            }
        except Exception:
            pass
        return None

    return _before_request
