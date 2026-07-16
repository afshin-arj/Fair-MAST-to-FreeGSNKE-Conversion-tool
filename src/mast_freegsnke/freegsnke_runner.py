from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence


@dataclass(frozen=True)
class ScriptRunResult:
    script: str
    ok: bool
    returncode: int
    duration_s: float
    stdout_path: str
    stderr_path: str
    python_exe: str
    error_hint: Optional[str] = None


def _default_python() -> str:
    return sys.executable


def _detect_import_error(stderr_text: str) -> Optional[str]:
    # Keep this conservative and deterministic.
    if "ModuleNotFoundError" in stderr_text and "freegsnke" in stderr_text:
        return "freegsnke_not_installed_in_selected_python"
    if "ImportError" in stderr_text and "freegsnke" in stderr_text:
        return "freegsnke_import_error"
    return None


class FreeGSNKERunner:
    """Execute generated FreeGSNKE scripts in a controlled, audit-friendly way.

    This runner does not assume FreeGSNKE is installed. If it is missing, execution
    is recorded deterministically with an actionable hint.
    """

    def __init__(self, python_exe: Optional[str] = None, env: Optional[Dict[str, str]] = None):
        raw = python_exe or _default_python()
        p = Path(raw)
        if not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        self.python_exe = str(p) if p.exists() else raw
        self.env = dict(os.environ)
        if env:
            self.env.update({str(k): str(v) for k, v in env.items()})

    def run_script(self, script_path: Path, run_dir: Path, label: str) -> ScriptRunResult:
        script_path = script_path.resolve()
        run_dir = run_dir.resolve()
        logs_dir = run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = logs_dir / f"{label}.stdout.txt"
        stderr_path = logs_dir / f"{label}.stderr.txt"

        t0 = time.time()
        proc = subprocess.run(
            [self.python_exe, str(script_path)],
            cwd=str(run_dir),
            env=self.env,
            text=True,
            capture_output=True,
        )
        dt = float(time.time() - t0)

        stdout_path.write_text(proc.stdout or "")
        stderr_path.write_text(proc.stderr or "")

        hint = _detect_import_error(proc.stderr or "")
        ok = proc.returncode == 0

        return ScriptRunResult(
            script=str(script_path.name),
            ok=ok,
            returncode=int(proc.returncode),
            duration_s=dt,
            stdout_path=str(stdout_path.relative_to(run_dir)),
            stderr_path=str(stderr_path.relative_to(run_dir)),
            python_exe=str(self.python_exe),
            error_hint=hint,
        )


def write_execution_report(run_dir: Path, report: Dict[str, Any]) -> Path:
    out = run_dir / "freegsnke_execution.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True))
    return out
