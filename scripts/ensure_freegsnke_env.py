#!/usr/bin/env python3
"""Ensure .venv-freegsnke exists and can import freegsnke (shot-only happy path).

configs/default.json points freegsnke_python at .venv-freegsnke/Scripts/python.exe.
run_pipeline.cmd/.sh call this so a fresh clone does not fail at FreeGSNKE execute.
"""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv-freegsnke"
REQ = ROOT / "requirements-freegsnke.txt"
MARKER = VENV / ".freegsnke_install_marker"


def _venv_python() -> Path:
    if platform.system().lower().startswith("win"):
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _req_hash() -> str:
    return hashlib.sha256(REQ.read_bytes()).hexdigest()


def _find_boot_python() -> list[str]:
    """Require Python 3.11 for FreeGSNKE wheels (scipy / freegs4e)."""

    def _is_311(cmd: list[str]) -> bool:
        try:
            chk = subprocess.run(
                cmd + ["-c", "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) else 1)"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return chk.returncode == 0
        except Exception:
            return False

    if platform.system().lower().startswith("win"):
        if _is_311(["py", "-3.11"]):
            return ["py", "-3.11"]
    for cand in ("python3.11", "python3", "python"):
        if _is_311([cand]):
            return [cand]
    raise RuntimeError(
        "Python 3.11 is required for .venv-freegsnke (FreeGSNKE/scipy wheels). "
        "Install Python 3.11 and retry. On Windows: py -3.11 …"
    )


def _import_ok(py: Path) -> bool:
    if not py.is_file():
        return False
    try:
        chk = subprocess.run(
            [str(py), "-c", "import freegsnke; print(getattr(freegsnke,'__version__','ok'))"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return chk.returncode == 0
    except Exception:
        return False


def main() -> int:
    if os.environ.get("RUN_PIPELINE_SKIP_FREEGSNKE_ENV", "").strip() == "1":
        print("[INFO] RUN_PIPELINE_SKIP_FREEGSNKE_ENV=1: skipping FreeGSNKE venv bootstrap")
        return 0
    if not REQ.is_file():
        print(f"[FAIL] missing {REQ}")
        return 2

    py = _venv_python()
    want = _req_hash()
    have = MARKER.read_text(encoding="utf-8").strip() if MARKER.is_file() else ""
    if py.is_file() and have == want and _import_ok(py):
        print(f"[OK] FreeGSNKE env ready: {py}")
        return 0

    try:
        boot = _find_boot_python()
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        return 4
    if not VENV.is_dir() or not py.is_file():
        print(f"[INFO] Creating FreeGSNKE venv: {VENV} (bootstrap: {' '.join(boot)})")
        rc = subprocess.run(boot + ["-m", "venv", str(VENV)], cwd=str(ROOT))
        if rc.returncode != 0:
            print("[FAIL] venv creation failed for .venv-freegsnke")
            return rc.returncode or 1
        py = _venv_python()

    print("[INFO] Upgrading pip in .venv-freegsnke")
    rc = subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=str(ROOT))
    if rc.returncode != 0:
        print("[FAIL] pip upgrade failed in .venv-freegsnke")
        return rc.returncode or 1

    print(f"[INFO] Installing FreeGSNKE stack from {REQ.name}")
    rc = subprocess.run([str(py), "-m", "pip", "install", "-r", str(REQ)], cwd=str(ROOT))
    if rc.returncode != 0:
        print("[FAIL] FreeGSNKE requirements install failed")
        print("[HINT] Use Python 3.11 (3.14 may lack scipy wheels). See HOW_TO_RUN.txt")
        return rc.returncode or 1

    if not _import_ok(py):
        print(f"[FAIL] freegsnke still not importable in {py}")
        return 3

    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(want + "\n", encoding="utf-8")
    print(f"[OK] FreeGSNKE env ready: {py}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
