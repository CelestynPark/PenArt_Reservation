from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional

from pymongo.errors import PyMongoError

from app.config import load_config
from app.core.constants import ErrorCode
from app.repositories.common import get_collection, map_pymongo_error
from app.services.i18n_service import t as i18n_t
from app.utils.time import now_utc, isoformat_utc

__all__ = ["send", "route", "with_backoff", "render_template", "register_adapter"]

MAX_RETRY = 3
BASE_DELAY_MS = 250

# ---- Adapters registry (tests can override via register_adapter) ----
_Adapter = Callable[[Dict[str, Any]], Dict[str, Any]]
_ADAPTERS: Dict[str, _Adapter] = {}


def register_adapter(channel: str, fn: _Adapter) -> None:
    if not isinstance(channel, str) or not Callable(fn):
        raise ValueError("invalid adapter")
    _ADAPTERS[channel.strip().lower()] = fn


def _default_ok(_: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "data": {"provider": "noop"}}


# prefill safe no-op adapter; tests/mocks can override
for _ch in ("email", "sms", "kakao"):
    _ADAPTERS.setdefault(_ch, _default_ok)


# ---- Helpers ----
def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def _err(code: str, message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if data:
        body["data"] = data
    return body


def _validate_payload(n: Dict[str, Any]) -> None:
    if not isinstance(n ,dict):
        raise ValueError("payload must be dict")
    for k in ("to", "channel", "template", "payload"):
        if k not in n:
            raise ValueError(f"missing field: {k}")
    if not isinstance(n["to"], (str, list)):
        raise ValueError("to must be string or list")
    if not isinstance(n["channel"], str):
        raise ValueError("channel must be string")
    if not isinstance(n["template"], str):
        raise ValueError("template must be string")
    if not isinstance(n["payload"], str):
        raise ValueError("payload must be object")
    

def _allowed_channel(ch: str) -> bool:
    cfg = load_config()
    return ch in set(cfg.alert_channels)


def _log_notification(rec: Dict[str, Any]) -> None:
    try:
        get_collection("notifications_log").insert_one(rec)
    except PyMongoError:
        # logging must not break primary flow
        pass


# ---- Template Rendering ----
def render_template(template: str, payload: Dict[str, Any], lang: str) -> str:
    # Use i18n bundle key first; fallbakc to .format on raw template
    msg = i18n_t(lang, template, payload)
    if msg == template:
        try:
            msg = template.format(**payload)
        except Exception:
            msg = template
    return msg


# ---- Channel routing ----
def route(channel: str) -> _Adapter:
    ch = (channel or "").strip().lower()
    if not ch or ch not in _ADAPTERS:
        raise ValueError("unknown channel")
    return _ADAPTERS[ch]


# ---- Backoff wrapper (single-attempt; caller/scheduler handles wait/retry) ----
def with_backoff(fn: _Adapter, *args: Any, attempt: int = 0, **kwargs: Any) -> Dict[str, Any]:
    try:
        res = fn(*args, **kwargs)
        if isinstance(res, dict) and res.get("ok"):
            return res
        # adapter returned failure-like structure
        msg = (res or {}).get("error", {}).get("message") if isinstance(res, dict) else "adapter failed"
        raise RuntimeError(msg or "adapter failed")
    except Exception as e:
        next_delay_ms = int(BASE_DELAY_MS * math.pow(2, max(0, attempt)))
        return _err(
            ErrorCode.ERR_INTERNAL.value,
            str(e),
            {"attempt": attempt, "next_delay_ms": next_delay_ms}
        )
    

# ---- Public API ----
def send(notification: Dict[str, Any], attempt: int = 0) -> Dict[str, Any]:
    try:
        _validate_payload(notification)
    except ValueError as e:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, str(e))
    
    to = notification["to"]
    channel = str(notification["channel"]).strip().lower()
    template = str(notification["template"]).strip()
    payload = dict(notification.get("payload") or {})
    lang = (notification.get("lang") or load_config().default_lang or "ko").strip().lower()

    if not _allowed_channel(channel):
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "channel not allowed")
    
    # Render content
    content = render_template(template, payload, lang)

    # Compose adapter input (normalized)
    nrm: Dict[str, Any] = {
        "to": to,
        "channel": channel,
        "template": template,
        "payload": payload,
        "lang": lang,
        "content": content
    }

    adapter = None
    try:
        adapter = route(channel)
    except ValueError:
        return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "unknown channel")
    
    # Single attempt with computed backoff on failure
    res = with_backoff(adapter, nrm, attempt=attempt)

    # Logging
    log_doc: Dict[str, Any] = {
        "to": to,
        "channel": channel,
        "template": template,
        "payload": payload,
        "lang": lang,
        "status": "sent" if res.get("ok") else "failed",
        "attempt": attempt,
        "at": isoformat_utc(now_utc())
    }
    if res.get("ok"):
        log_doc["result"] = res.get("data")
    else:
        log_doc["error"] = res.get("error")
        # If eligible for next retry, compute and include
        if attempt + 1 < MAX_RETRY:
            next_delay_ms = int(BASE_DELAY_MS * math.pow(2, max(0, attempt)))
            log_doc["next_delay_ms"] = next_delay_ms
    _log_notification(log_doc)

    if res.get("ok"):
        data = {
            "channel": channel,
            "status": "sent",
            "attempt": attempt
        }
        # bubble up adapter metadata if any
        if isinstance(res.get("data"), dict):
            for k, v in res["data"].items():
                if k not in data:
                    data[k] = v
        return _ok(data)
    
    # adapter failed
    next_delay_ms = int(BASE_DELAY_MS * math.pow(2, max(0, attempt)))
    data = {"attempt": attempt, "next_delay_ms": next_delay_ms}
    # If reached max retry, include terminal flag
    if attempt + 1 >= MAX_RETRY:
        data["terminal"] = True
    err = res.get("error") or {"code": ErrorCode.ERR_INTERNAL.value, "message": "send failed"}
    return _err(err.get("code", ErrorCode.ERR_INTERNAL.value), err.get("message", "send failed"), data)
