from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


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
    timed_out: bool = False
    timeout_s: Optional[float] = None


def _default_python() -> str:
    return sys.executable


def resolve_freegsnke_python(configured: Optional[str], repo_root: Optional[Path] = None) -> str:
    """Resolve FreeGSNKE interpreter path portably across Windows/POSIX venvs."""
    if not configured:
        return _default_python()
    root = repo_root or Path.cwd()
    p = Path(configured)
    if not p.is_absolute():
        p = (root / p).resolve()
    if p.exists():
        return str(p)
    # Allow configs/default.json to ship a Windows-style path while still working
    # on POSIX (and vice versa) when the sibling venv layout exists.
    name = p.name.lower()
    parent = p.parent
    candidates: list[Path] = []
    if name in {"python.exe", "python"}:
        venv_root = parent.parent if parent.name.lower() in {"scripts", "bin"} else parent
        candidates.extend(
            [
                venv_root / "Scripts" / "python.exe",
                venv_root / "bin" / "python",
                venv_root / "bin" / "python3",
            ]
        )
    for cand in candidates:
        if cand.exists():
            return str(cand.resolve())
    return str(p)


def _prepend_pythonpath(env: Dict[str, str], entries: list[Path]) -> Dict[str, str]:
    """Prepend existing source trees so FreeGSNKE scripts can import mast_freegsnke."""
    out = dict(env)
    parts: list[str] = []
    for p in entries:
        if p.is_dir():
            parts.append(str(p.resolve()))
    if not parts:
        return out
    existing = out.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    out["PYTHONPATH"] = os.pathsep.join(parts)
    return out


def resolve_repo_src(repo_root: Optional[Path] = None) -> Optional[Path]:
    """Locate package ``src/`` so presentation + introspection import in the FreeGSNKE venv."""
    if repo_root is not None:
        cand = Path(repo_root) / "src"
        if (cand / "mast_freegsnke").is_dir():
            return cand
    # freegsnke_runner.py → mast_freegsnke → src → repo
    here = Path(__file__).resolve()
    pkg_src = here.parents[1]  # .../src
    if (pkg_src / "mast_freegsnke").is_dir():
        return pkg_src
    return None


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

    A hard wall-clock ``timeout_s`` (v10.5.0) prevents indefinite hangs when the
    FreeGSNKE inverse residual-resize loop never returns (known failure mode when
    Inverse_optimizer state is reused across times).

    ``repo_root`` / package ``src`` is prepended to PYTHONPATH so scripts can import
    ``mast_freegsnke`` (presentation GIFs, solver introspection) even when the
    FreeGSNKE venv only has freegsnke+deps installed.
    """

    def __init__(
        self,
        python_exe: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_s: Optional[float] = None,
        repo_root: Optional[Path] = None,
    ):
        self.python_exe = resolve_freegsnke_python(python_exe, repo_root=repo_root)
        self.env = dict(os.environ)
        # Unbuffered child stdout so long FreeGSNKE inits (nl_solver) appear in logs.
        self.env.setdefault("PYTHONUNBUFFERED", "1")
        if env:
            self.env.update({str(k): str(v) for k, v in env.items()})
        src = resolve_repo_src(repo_root)
        if src is not None:
            self.env = _prepend_pythonpath(self.env, [src])
        self.timeout_s = float(timeout_s) if timeout_s is not None else None
        self.repo_src = src

    def run_script(self, script_path: Path, run_dir: Path, label: str) -> ScriptRunResult:
        script_path = script_path.resolve()
        run_dir = run_dir.resolve()
        logs_dir = run_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        stdout_path = logs_dir / f"{label}.stdout.txt"
        stderr_path = logs_dir / f"{label}.stderr.txt"

        t0 = time.time()
        timed_out = False
        try:
            proc = subprocess.run(
                [self.python_exe, str(script_path)],
                cwd=str(run_dir),
                env=self.env,
                text=True,
                capture_output=True,
                timeout=self.timeout_s,
            )
            returncode = int(proc.returncode)
            stdout_text = proc.stdout or ""
            stderr_text = proc.stderr or ""
        except subprocess.TimeoutExpired as e:
            timed_out = True
            returncode = 124
            stdout_text = (e.stdout.decode("utf-8", errors="replace") if isinstance(e.stdout, (bytes, bytearray)) else (e.stdout or ""))
            stderr_text = (e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, (bytes, bytearray)) else (e.stderr or ""))
            stderr_text += (
                f"\n[TIMEOUT] FreeGSNKE script exceeded wall-clock limit "
                f"of {self.timeout_s}s (label={label}); process killed.\n"
            )
        dt = float(time.time() - t0)

        stdout_path.write_text(stdout_text)
        stderr_path.write_text(stderr_text)

        hint = _detect_import_error(stderr_text)
        if timed_out:
            hint = "freegsnke_script_timeout"
        ok = (returncode == 0) and (not timed_out)

        return ScriptRunResult(
            script=str(script_path.name),
            ok=ok,
            returncode=returncode,
            duration_s=dt,
            stdout_path=str(stdout_path.relative_to(run_dir)),
            stderr_path=str(stderr_path.relative_to(run_dir)),
            python_exe=str(self.python_exe),
            error_hint=hint,
            timed_out=timed_out,
            timeout_s=self.timeout_s,
        )


def write_execution_report(run_dir: Path, report: Dict[str, Any]) -> Path:
    out = run_dir / "freegsnke_execution.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True))
    return out
