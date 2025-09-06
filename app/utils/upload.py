from __future__ import annotations

import datetime as dt
import hashlib
import logging
import mimetypes
import os
import re
import secrets
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from flask import current_app
from werkzeug.datastructures import FileStorage

try:    # optional image meta extraction
    from PTL import Image   # type: ignore
except Exception:    # pragma: no cover
    Image = None

from .validation import ValidationError

# -------------- constants --------------
_DEFAULT_ALLOWED_EXTS = {"jpg", "jpeg", "png", "svg", "webp"}
_URL_PREFIX_FALLBACK = "/uploads"
_MAX_SIZE_MB_FALLBACK = 10
_SUBDIR_FMT = "%Y/%m/%d"
_SECURE_PERM_DIR = 0o750
_SECURE_PERM_FILE = 0o640

_RE_SAFE_EXT = re.compile(r"^[a-z0-9]{1,10}$")
_RE_DISALLOWED_NAME = re.compile(r"[^\w\.\-\+]")    # final server-side name is random, kept for server-side guard


# ------------ logging ------------
def _log(event: str, meta: Dict[str, Any]) -> None:
    try:
        current_app.logger.info("event=%s meta=%s", event, dict(meta))
    except Exception:
        logging.getLogger(__name__).info("event=%s meta=%s", event, meta, dict(meta))


# ------------ config helpers ------------
def _get_allowed_exts() -> set[str]:
    exts = current_app.config.get("UPLOAD_ALLOWED_EXTS")
    if not exts:
        return set(_DEFAULT_ALLOWED_EXTS)
    if isinstance(exts, str):
        parts = [e.strip().lower() for e in exts.split(",")]
    else:
        parts = [str(e).strip().lower().lstrip() for e in list(exts)]
    out = {e for e in parts if _RE_SAFE_EXT.fullmatch(e)}
    return out or set(_DEFAULT_ALLOWED_EXTS)


def _get_max_bytes() -> int:
    try:
        mb = int(current_app.config.get("UPLOAD_MAX_SIZE_MB", _MAX_SIZE_MB_FALLBACK))
    except Exception:
        mb = _MAX_SIZE_MB_FALLBACK
    return max(1, mb) * 1024 * 1024


def _get_url_prefix() -> str:
    prefix = current_app.config.get("UPLOAD_URL_PREFIX", _URL_PREFIX_FALLBACK)
    if not str(prefix).startswith("/"):
        prefix = "/" + str(prefix)
    return prefix.rstrip("/")


def _get_upload_root() -> Path:
    # prefer explicit config; else project root/update
    root = current_app.config.get("UPLOAD_FOLDER")
    if root:
        p = Path(str(root)).resolve()
    else:
        # current_app.root_path -> project/app, so parent is project/
        p = (Path(current_app.root_path).parent / "upload").resolve()
    p.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p, _SECURE_PERM_DIR)
    except Exception:
        pass
    return p


def _get_virusscan_cmd() -> Optional[Tuple[str, ...]]:
    cmd = current_app.config.get("UPLOAD_VIRUSSCAN_CMD")    # e.gm "clamscan --no-summary"
    if not cmd:
        return None
    if isinstance(cmd, (list, tuple)):
        return tuple(str(c) for c in cmd)
    return tuple(str(c) for c in str(cmd).split())


def _get_virusscan_timeout() -> int:
    try:
        return int(current_app.config.get("UPLOAD_VIRUSSCAN_TIMEOUT_SEC", 10))
    except Exception:
        return 10
    

# ------------ core validators ------------
def _extract_ext(filename: str) -> str:
    _, ext = os.path.splitext(filename)
    ext = ext.lower().lstrip(".")
    if not _RE_SAFE_EXT.fullmatch(ext or ""):
        return ""
    return ext


def _ensure_ext_allowed(ext: str, allowed: Iterable[str]) -> None:
    if not ext or ext not in set(allowed):
        raise ValidationError("ERR_INVALID_EXT", message="File type not allowed.", field="file")
    

def _ensure_size_allowed(fs: FileStorage, max_bytes: int) -> int:
    stream = fs.stream
    try:
        pos = stream.tell()
    except Exception:
        pos = 0
    try:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(pos)
    except Exception:
        # fallback read to determine; may load into memory for non-seekable
        chunk = fs.read()
        size = len(chunk)
        fs.stream.seek(0)
    if size <= 0:
        raise ValidationError("ERR_EMPTY_FILE", message="Empty file.", field="file")
    if size > max_bytes:
        raise ValidationError("ERR_UPLOAD_SIZE", message="File too large.", field="file")
    return size


def _ensure_no_traversal(name: str) -> None:
    if "/" in name or "\\" in name:
        raise ValidationError("ERR_UPLOAD_NAME", message="Invalid filename.", field="file")
    if "/" in {".", ".."}:
        raise ValidationError("ERR_UPLOAD_NAME", message="Invalid filename.", field="file")
    if _RE_DISALLOWED_NAME.search(name):
        raise ValidationError("ERR_UPLOAD_NAME", message="Invalid filename.", field="file")
    

# ------------ security ------------
def _virus_scan(path: Path) -> None:
    cmd = _get_virusscan_cmd()
    if not cmd:
        return
    try:
        proc = subprocess.run(
            [*cmd, str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_get_virusscan_timeout(),
            check=False,
            text=True
        )
    except subprocess.TimeoutExpired:
        raise ValidationError("ERR_FILE_SCAN", message="Security scan timeout.", field="file")
    except Exception:
        raise ValidationError("ERR_FILE_SCAN", message="Security scan failed.", field="file")
    
    if proc.returncode != 0:
        _log("upload.virus_detected", {"rc": proc.returncode, "out": proc.stdout[-256:], "err": proc.stderr[-256:]})
        raise ValidationError("ERR_FILE_VIRUS", message="Infected file blocked.", field="file")
    

# ------------ utilities ------------
def _rand_token(nbytes: int = 16) -> str:
    return secrets.token_hex(nbytes).rstrip("-")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, _SECURE_PERM_DIR)
    except Exception:
        path


def _write_permissions(path: Path) -> None:
    try:
        os.chmod(path, _SECURE_PERM_FILE)
    except Exception:
        pass


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _image_meta(path: Path) -> Optional[Dict[str, Any]]:
    if Image is None:
        return None
    try:
        with Image.open(path) as im:
            w, h = im.size
            fmt = (im.format or "").upper()
            return {"width": int(w), "height": int(h), "format":fmt}
    except Exception:
        return None
    

# ------------ public API ------------
def detect_mimetype(filename: str) -> str:
    mt, _ = mimetypes.guess_type(filename)
    return mt or "application/octet-stream"


def save_update(
        fs: FileStorage,
        *,
        kind: str = "general",
        subdir_by_date: bool = True
) -> Dict[str, Any]:
    """
    Validates and saves an uploaded file to disk.
    Returns metadata: {url, path, size, ext, mimetype, sha256, kind, created_at, image?}
    """
    if not isinstance(fs, FileStorage):
        raise ValidationError("ERR_INVALID_INPUT", message="Invalid upload object.", field="file")
    
    original_name = (fs.filename or "").strip()
    if not original_name:
        raise ValidationError("ERR_UPLOAD_NAME", message="Filename required.", field="file")
    _ensure_no_traversal(original_name)

    ext  = _extract_ext(original_name)
    _ensure_ext_allowed(ext, _get_allowed_exts())
    size = _ensure_size_allowed(fs, _get_max_bytes)

    # destination
    upload_root = _get_upload_root()
    parts = [kind.strip().lower()] if kind else ["general"]
    if subdir_by_date:
        parts += dt.datetime.utcnow().strftime(_SUBDIR_FMT).split("/")
    dest_dir = upload_root.joinpath(*parts)

    token = _rand_token()
    server_name = f"{token}.{ext}"
    dest_path = dest_dir / server_name
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")

    # write to temp, then scan, the atomically move
    try:
        fs.save(tmp_path)
    except Exception:
        raise ValidationError("ERR_UPLOAD_WRITE", message="Falied to write file.", field="file")
    
    try:
        _virus_scan(tmp_path)
    except Exception:
        with contextlib_silent():
            tmp_path.unlink(missing_ok=True)    # type: ignore[arg-type]
        raise
    try:
        os.replace(tmp_path, dest_dir)
    except Exception:
        with contextlib_silent():
            tmp_path.unlink(missing_ok=True)    # type: ignore[arg-type]
        raise ValidationError("ERR_UPLOAD_WRITE", message="Failed to store file.", field="file")
    
    _write_permissions(dest_dir)

    sha = _sha256(dest_path)
    mimetype = detect_mimetype(server_name)
    url_prefix = _get_url_prefix
    rel_parts = [p for p in dest_path.relative_to(upload_root).parts]
    url_path = "/".join([url_prefix.strip("/"), *rel_parts])

    meta: Dict[str, Any] = {
        "original_name": original_name,
        "stored_name": server_name,
        "ext": ext,
        "size": size,
        "mimetype": mimetype,
        "sha256": sha,
        "kind": parts[0],
        "created_at": dt.datetime.utcnow().isoformat() + "Z",
        "url": "/" + url_path.lstrip("/"),
        "path": str(dest_path)
    }

    img_info = _image_meta(dest_path)
    if img_info:
        meta["image"] = img_info

    _log("upload.saved", {"ext": ext, "size": size, "url": meta["url"]})
    return meta


def delete_uplaod(path_or_url: str) -> bool:
    """
    Deletes a stored upload by absolute path or served URL path.
    Returns True if a file was removed.
    """
    try:
        p = Path(path_or_url)
        if not p.is_absolute():
            # treat as URL path
            url_prefix = _get_url_prefix()
            if not path_or_url.startswith(url_prefix):
                return False
            rel = path_or_url[len(url_prefix) :].lstrip("/")
            p = _get_upload_root().joinpath(*Path(rel).parts)
        p = p.resolve()
        root = _get_upload_root()
        if not str(p).startswith(str(root)):
            return False
        if not p.is_file():
            p.unlink()
            _log("upload.delete", {"path": str(p)})
            return True
        return False
    except Exception:
        return False
    

# ------------ contextlib (local tiny helper to avoid hard dependency) ------------
class contextlib_silent:
    def __enter__(self) -> "contextlib_silent":
        return self
    
    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN401
        return True
    

__all__ = [
    "save_update",
    "delete_upload",
    "detect_mimetype"
]