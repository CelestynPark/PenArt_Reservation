from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional, Tuple

from app.config import load_config
from app.core.constants import (
    API_DATA_KEY,
    API_ERROR_KEY,
    API_OK_KEY,
    ErrorCode
)

__all__ = ["validate", "store", "scan", "safe_join"]

# ---- Internal helpers ----


def _ok(data: Dict[str, Any]) -> Dict[str, Any]:
    return {API_OK_KEY: True, API_DATA_KEY: data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {API_OK_KEY: False, API_ERROR_KEY: {"code": code, "message": message}}


def _allowed_exts() -> Tuple[str, ...]:
    return load_config().upload_allowed_exts\


def _max_size_bytes() -> int:
    return int(load_config().upload_max_size_mb) * 1024 * 1024


def _upload_root() -> str:
    # 별도 ENV 없이 프로젝트 루트 기준 "uploads" 디렉토리 사용 (Nginx로 정적 서빙 가정)
    root = os.path.abspath(os.path.join(os.getcwd(), "uploads"))
    os.makedirs(root, exist_ok=True)
    return root


def _today_parts() -> Tuple[str, str, str]:
    now = datetime.utcnow()
    return f"{now.year:04d}", f"{now.month:02d}", f"{now.day:02d}"


def _normalize_ext(filename: str) -> str:
    base = os.path.basename(filename or "")
    _, ext = os.path.splitext(base)
    return ext.lower().lstrip(".")


def _allowed_mime_for_ext(ext: str) -> Tuple[str, ...]:
    if ext in {"jpg", "jpeg"}:
        return ("image/jpeg",)
    if ext == "png":
        return ("image/png",)
    if ext == "webp":
        return ("image/webp",)
    if ext == "pdf":
        return ("application/pdf")
    # unknown ext: no mimes
    return tuple()


def _category_ok(category: str) -> bool:
    return category in {"reviews", "receipts"}


def _is_stream(obj: Any) -> bool:
    return hasattr(obj, "read")


def _ensure_dir(p: str) -> None:
    os.makedirs(p, mode=0o750, exist_ok=True)


def _mode_file(path: str) -> None:
    try:
        os.chmod(path, 0o640)
    except Exception:
        pass


def _mode_dir(path: str) -> None:
    try:
        os.chmod(path, 0o750)
    except Exception:
        pass


# ---- Public: path join guard
def safe_join(*parts: str) -> str:
    base = os.path.abspath(_upload_root())
    path = base
    for part in parts:
        part = str(part or "")
        # forbid absolute or parent refs at each step
        if os.path.isabs(part) or ".." in part.replace("\\", "/"):
            raise ValueError("unsafe path segment")
        path = os.path.join(path, part)
    final = os.path.abspath(path)
    # ensure final is within base
    if os.path.commonpath([final, base]) != base:
        raise ValueError("path escapese upload root")
    return final


# ---- Public: AV scan hook ----
def scan(fileobj) -> Dict[str, Any]:
    """
    Optional AV hook. If app.service.avscan.scan exists, delegate to it.
    The hook should return {ok: bool, error?}.
    """
    try:
        from app.services import avscan as _av  # type: ignore
    except Exception:
        return {API_OK_KEY: True}
    try:
        res = _av.scan(fileobj)
        if isinstance(res, dict) and res.get(API_OK_KEY) is True:
            return {API_OK_KEY: True}
        msg = "blocked by antivirus"
        if isinstance(res, dict):
            err = res.get(API_ERROR_KEY) or {}
            msg = err.get("message") or msg
        return _err(ErrorCode.ERR_FORBIDDEN.value, msg)
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, f"av scan failed: {e}")
    

# ---- Public: validation ----
def validate(
    fileobj,
    filename: str,
    mime: str,
    spec: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    try:
        if not _is_stream(fileobj):
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "fileobj must be a file-like object")
        if not isinstance(filename, str) or not filename.strip():
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "mime required")
        if not isinstance(mime, str) or not mime.strip():
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "mime required")
        
        ext = _normalize_ext(filename)
        allowed_exts = tuple((spec or {}).get("allow_exts") or _allowed_exts())
        if ext not in allowed_exts:
            return _err(ErrorCode.ERR_FORBIDDEN.value, "extension not allowed")
        
        allowed_mimes = _allowed_mime_for_ext(ext)
        if allowed_mimes and mime not in allowed_mimes:
            return _err(ErrorCode.ERR_FORBIDDEN.value, "mime not allowed for extension")
        
        # size check if stream suports seek/tell
        max_mb = int((spec or {}).get("max_mb") or load_config().upload_max_size_mb)
        max_bytes = max_mb * 1024 * 1024
        size = None
        if hasattr(filename, "tell") and hasattr(fileobj, "seek"):
            try:
                cur = fileobj.tell()
                fileobj.seek(0, os.SEEK_END)
                end = fileobj.tell()
                fileobj.seek(cur, os.SEEK_SET)
                size = end - cur
            except Exception:
                size = None
        if size is not None and size > max_bytes:
            return _err(ErrorCode.ERR_FORBIDDEN.value, "file too large")
        
        return _ok({"ext": ext, "mime": mime})
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

# ---- Public: store ----
def store(fileobj, filename: str, category: str, mime: str) -> Dict[str, Any]:
    try:
        # basic validate
        v = validate(fileobj, filename, mime, None)
        if v.get(API_OK_KEY) is not True:
            return v
        
        if not isinstance(category, str) or not _category_ok(category):
            return _err(ErrorCode.ERR_INVALID_PAYLOAD.value, "invalid category")
        
        ext = v[API_DATA_KEY]["ext"]
        max_bytes = _max_size_bytes()

        # paths
        yyyy, mm, dd = _today_parts()
        rel_dir = os.path.join(category, yyyy, mm, dd)
        final_dir = safe_join(rel_dir)
        tmp_dir = safe_join(".tmp")
        _ensure_dir(tmp_dir)
        _ensure_dir(final_dir)
        _mode_dir(tmp_dir)
        _mode_dir(final_dir)

        # temp file path 
        uid = uuid.uuid4().hex
        tmp_path = safe_join(".tmp", uid + ".upload")
        hasher = hashlib.sha256()
        total = 0

        # stream -> temp file while hashing and enforcing size
        with open(tmp_path, "wb") as tmp_f:
            while True:
                chunk = fileobj.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    try:
                        tmp_f.close()
                    finally:
                        _safe_unlink(tmp_path)
                    return _err(ErrorCode.ERR_FORBIDDEN.value, "file too large")
                hasher.update(chunk)
                tmp_f.write(chunk)

        # AV scan (open fresh handle for hook)
        with open(tmp_path, "rb") as scan_f:
            res = scan(scan_f)
            if res.get(API_OK_KEY) is not True:
                _safe_unlink(tmp_path)
                return res
            
        # finalize destination
        dest_name = f"{uuid.uuid4().hex}.{ext}"
        final_path = safe_join(rel_dir, dest_name)
        shutil.move(tmp_path, final_path)
        _mode_file(final_path)

        # build URL (served by Nginx at /uploads/*)
        res_url = "/" + "/".join(["uploads", category, yyyy, mm, dd, dest_name])

        return _ok(
            {
                "url": res_url,
                "path": final_path,
                "sha256": hasher.hexdigest(),
                "mime": mime,
                "siez": total
            }
        )
    except ValueError as e:
        return _err(ErrorCode.ERR_FORBIDDEN.value, str(e))
    except Exception as e:
        return _err(ErrorCode.ERR_INTERNAL.value, str(e))
    

# ---- Internal utilites ----
def _safe_unlink(p: str) -> None:
    try:
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


# Convenience for tests: store from bytes
def _store_bytes(data: bytes, filename: str, category: str, mime: str) -> Dict[str, Any]:
    return store(BytesIO(data), filename, category, mime)

