from __future__ import annotations
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import hashlib

def sha256_file(path: Path, chunk_bytes: int = 1024 * 1024) -> str:
    """Compute SHA256 of a file deterministically."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk_bytes)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _is_windows_replace_lock(exc: BaseException) -> bool:
    """True when os.replace failed because another process still has the dest open.

    On Windows, readers opened without FILE_SHARE_DELETE (Python's default open)
    block atomic replace with WinError 5 (access denied) or 32 (sharing violation).
    """
    if not isinstance(exc, OSError):
        return False
    winerr = getattr(exc, "winerror", None)
    if winerr in (5, 32):
        return True
    # Non-Windows / errno fallbacks (EACCES / EBUSY / EPERM).
    return getattr(exc, "errno", None) in (13, 16, 1)


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    """Atomic JSON write (temp + replace) so concurrent readers never see a partial file.

    Retries replace on Windows reader locks (UI polling ``progress.json`` / AV).
    Falls back to a direct overwrite only after retries are exhausted so a live
    Dash poll cannot abort the pipeline mid-stage.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(obj, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    last: BaseException | None = None
    try:
        tmp.write_text(payload, encoding="utf-8")
        for attempt in range(10):
            try:
                os.replace(tmp, path)
                return
            except OSError as e:
                last = e
                if not _is_windows_replace_lock(e):
                    raise
                time.sleep(0.05 * (attempt + 1))
        # Last resort: non-atomic overwrite (brief partial-read window for pollers).
        try:
            path.write_text(payload, encoding="utf-8")
            return
        except OSError as e:
            last = e
            raise PermissionError(
                f"Could not write {path} after retries (likely locked by another process): {last}"
            ) from last
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass

def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p

def shot_cache_dir(cache_root: Path, shot: int) -> Path:
    """Single source of truth for the per-shot download cache layout (data_cache/shot_<N>)."""
    return Path(cache_root) / f"shot_{shot}"

def run_cmd(cmd: List[str], timeout_s: int | None = 60) -> Tuple[int, str]:
    """Run a command and capture combined stdout/stderr.

    Returns (rc, output). On timeout, rc=124 and output contains a marker.
    """
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_s,
        )
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "")
        out += "\n[TIMEOUT] command exceeded {}s\n".format(timeout_s)
        return 124, out
def looks_like_exists_s5cmd_ls(output: str) -> bool:
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if not lines:
        return False
    if all(ln.upper().startswith("ERROR") for ln in lines):
        return False
    return True


def resolve_s5cmd_path(configured: str, repo_root: Path | None = None) -> str:
    """Resolve s5cmd executable: absolute/PATH hit, else repo tools/s5cmd(.exe)."""
    import shutil

    p = Path(configured)
    if p.is_file():
        return str(p.resolve())
    which = shutil.which(configured)
    if which:
        return which
    root = repo_root or Path.cwd()
    for cand in (root / "tools" / "s5cmd.exe", root / "tools" / "s5cmd"):
        if cand.is_file():
            return str(cand.resolve())
    return configured
