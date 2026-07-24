from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .util import ensure_dir, sha256_file, write_json


# Directories that must never be hashed into run provenance (archives, caches, venvs).
_DEFAULT_HASH_EXCLUDE = (
    ".git",
    "__pycache__",
    ".pytest_cache",
    "provenance",
    "history",
    ".multitime_work",
    ".venv",
    ".venv-freegsnke",
)


def _is_reparse_point(path: Path) -> bool:
    """True for symlinks and Windows junctions/mount-points (layout shims)."""
    try:
        if path.is_symlink():
            return True
        if os.name == "nt":
            st = path.lstat()
            # FILE_ATTRIBUTE_REPARSE_POINT = 0x400
            return bool(getattr(st, "st_file_attributes", 0) & 0x400)
    except OSError:
        return True
    return False


def _iter_files(root: Path, exclude_dirs: Tuple[str, ...] = _DEFAULT_HASH_EXCLUDE) -> Iterable[Path]:
    """Yield regular files under ``root`` without following junctions or excluded dirs.

    Windows layout junctions under ``history/`` keep absolute targets into the live
    run tree. After a re-run archives ``06_authorities/``, those junctions break and
    ``Path.rglob`` / ``os.scandir`` into them raises ``FileNotFoundError``. Prune
    ``history`` (and other excludes) *before* descending, and never follow reparse
    points.
    """
    root = Path(root)
    exclude = set(exclude_dirs)
    if not root.is_dir():
        return

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        base = Path(dirpath)
        # Prune in-place so os.walk never descends into excluded / reparse dirs.
        keep: List[str] = []
        for name in dirnames:
            if name in exclude:
                continue
            child = base / name
            if _is_reparse_point(child):
                continue
            keep.append(name)
        dirnames[:] = keep

        for name in filenames:
            fp = base / name
            try:
                if _is_reparse_point(fp):
                    continue
                if not fp.is_file():
                    continue
            except OSError:
                continue
            yield fp


def hash_tree(root: Path, exclude_dirs: Tuple[str, ...] = _DEFAULT_HASH_EXCLUDE) -> Dict[str, Any]:
    root = Path(root)
    files: Dict[str, str] = {}
    skipped: List[Dict[str, str]] = []
    total_bytes = 0
    for p in _iter_files(root, exclude_dirs=exclude_dirs):
        try:
            rel = str(p.relative_to(root)).replace(os.sep, "/")
        except ValueError:
            continue
        try:
            files[rel] = sha256_file(p)
            total_bytes += p.stat().st_size
        except OSError as e:
            skipped.append({"path": rel, "error": f"{type(e).__name__}: {e}"})
    out: Dict[str, Any] = {
        "root": str(root),
        "n_files": len(files),
        "total_bytes": int(total_bytes),
        "sha256": files,
    }
    if skipped:
        out["skipped"] = skipped
        out["n_skipped"] = len(skipped)
    return out


def env_fingerprint() -> Dict[str, Any]:
    return {
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version.replace("\n", " "),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "system": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
    }


def pip_freeze(python_exe: Optional[str] = None) -> Dict[str, Any]:
    py = python_exe or sys.executable
    try:
        out = subprocess.check_output([py, "-m", "pip", "freeze"], text=True, stderr=subprocess.STDOUT)
        return {"ok": True, "python": py, "packages": [ln.strip() for ln in out.splitlines() if ln.strip()]}
    except Exception as e:
        return {"ok": False, "python": py, "error": f"{type(e).__name__}: {e}"}


def git_state(repo_root: Path) -> Dict[str, Any]:
    repo_root = Path(repo_root)
    def _run(args: List[str]) -> Tuple[bool, str]:
        try:
            out = subprocess.check_output(args, cwd=repo_root, text=True, stderr=subprocess.STDOUT).strip()
            return True, out
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    ok, commit = _run(["git", "rev-parse", "HEAD"])
    ok2, status = _run(["git", "status", "--porcelain"])
    return {"ok": bool(ok and ok2), "commit": commit if ok else None, "dirty": bool(status) if ok2 else None, "status_porcelain": status if ok2 else None}


def write_provenance(run_dir: Path, repo_root: Path, hash_data_tree: Optional[Path] = None) -> Dict[str, Any]:
    """Write provenance folder and return summary.

    Always hashes run_dir (excluding provenance / history / layout shims) and captures
    env + pip freeze. Optionally hashes a data tree (e.g. downloaded cache) if
    ``hash_data_tree`` is provided.
    """
    run_dir = Path(run_dir)
    prov_path = run_dir / "provenance"
    # Prior layouts leave ``provenance`` as a Windows junction into
    # ``06_authorities/provenance``. If that target was archived/moved, mkdir fails
    # with WinError 183 — drop the shim and create a real directory.
    if _is_reparse_point(prov_path):
        try:
            prov_path.unlink()
        except OSError:
            try:
                prov_path.rmdir()
            except OSError:
                pass
    prov_dir = ensure_dir(prov_path)

    # Hash run artifacts excluding provenance + archived history (Windows junctions
    # under history/ previously caused PermissionError / FileNotFoundError on re-runs).
    file_hashes = hash_tree(run_dir, exclude_dirs=_DEFAULT_HASH_EXCLUDE)
    write_json(prov_dir / "file_hashes.json", file_hashes)

    env = env_fingerprint()
    write_json(prov_dir / "env_fingerprint.json", env)

    pf = pip_freeze()
    write_json(prov_dir / "requirements.freeze.json", pf)

    gs = git_state(repo_root)
    write_json(prov_dir / "repo_state.json", gs)

    data_hashes = None
    if hash_data_tree is not None:
        data_hashes = hash_tree(hash_data_tree)
        write_json(prov_dir / "data_hashes.json", data_hashes)

    return {
        "ok": True,
        "provenance_dir": str(prov_dir),
        "file_hashes": {"n_files": file_hashes.get("n_files"), "total_bytes": file_hashes.get("total_bytes")},
        "data_hashed": bool(hash_data_tree is not None),
    }


def write_manifest_v2(run_dir: Path, base_manifest: Dict[str, Any], provenance_summary: Dict[str, Any], machine_snapshot: Optional[Dict[str, Any]]) -> Path:
    """Write manifest_v2.json into run_dir/provenance and return its path."""
    run_dir = Path(run_dir)
    prov_dir = ensure_dir(run_dir / "provenance")
    m2 = {
        "schema_version": "2.0",
        "shot": base_manifest.get("shot"),
        "created_utc": base_manifest.get("created_utc"),
        "status": base_manifest.get("status"),
        "blocking_errors": base_manifest.get("blocking_errors"),
        "stage_log": base_manifest.get("stage_log"),
        "inputs": {
            "machine_dir": base_manifest.get("machine_dir"),
            "required_groups": base_manifest.get("required_groups"),
            "level2_s3_prefix": base_manifest.get("level2_s3_prefix"),
        },
        "time_window": base_manifest.get("time_window"),
        "contracts": {
            "diagnostic_contracts_resolved": str(Path(run_dir) / "contracts" / "diagnostic_contracts.resolved.json"),
            "coil_map_resolved": str(Path(run_dir) / "contracts" / "coil_map.resolved.json"),
        },
        "machine_authority_snapshot": machine_snapshot,
        "provenance": provenance_summary,
    }
    out = prov_dir / "manifest_v2.json"
    write_json(out, m2)
    return out
