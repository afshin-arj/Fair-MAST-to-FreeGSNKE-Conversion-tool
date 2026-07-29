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


def _detect_evolutive_timeout_hint(stdout_text: str, stderr_text: str) -> Optional[str]:
    """Distinguish per-step nlstepper kill from global script wall-clock timeout."""
    blob = f"{stdout_text or ''}\n{stderr_text or ''}"
    if "per_step_timeout_s=" in blob and "[TIMEOUT] evolutive nlstepper" in blob:
        return "evolutive_per_step_timeout"
    if "[ABORT] evolutive Ip collapsed" in blob:
        return "evolutive_ip_collapse_abort"
    return None


def _force_kill_process_tree(pid: int) -> None:
    """Best-effort kill of ``pid`` and descendants (Windows orphans otherwise)."""
    if pid is None or int(pid) <= 0:
        return
    pid = int(pid)
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception:
            pass
        return
    try:
        os.kill(pid, 9)
    except Exception:
        pass
    # POSIX: try process-group kill when the child was started in a new session.
    try:
        os.killpg(pid, 9)
    except Exception:
        pass


class FreeGSNKERunner:
    """Execute generated FreeGSNKE scripts in a controlled, audit-friendly way.

    This runner does not assume FreeGSNKE is installed. If it is missing, execution
    is recorded deterministically with an actionable hint.

    A hard wall-clock ``timeout_s`` (v10.5.0) prevents indefinite hangs when the
    FreeGSNKE inverse residual-resize loop never returns (known failure mode when
    Inverse_optimizer state is reused across times).

    Logs are written via file handles (not PIPE). On Windows, multitime
    ``multiprocessing`` children can outlive a killed inverse/forward parent and
    keep inherited PIPEs open — ``subprocess.run(capture_output=True)`` then
    waits forever for EOF. File redirection + ``taskkill /T`` closes that hole.

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
        # Pin BLAS/OpenMP to one thread unless the user already set them.
        # Multi-threaded OpenBLAS/MKL has caused indefinite hangs in FreeGSNKE
        # nlstepper on Windows for some MAST shots (e.g. 30202 step stalls).
        for key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            self.env.setdefault(key, "1")
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
        returncode = -1
        creationflags = 0
        if os.name == "nt":
            # New process group so taskkill /T can tear down multitime grandchildren.
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        with open(stdout_path, "w", encoding="utf-8", errors="replace") as out_f, open(
            stderr_path, "w", encoding="utf-8", errors="replace"
        ) as err_f:
            proc = subprocess.Popen(
                [self.python_exe, str(script_path)],
                cwd=str(run_dir),
                env=self.env,
                stdout=out_f,
                stderr=err_f,
                text=True,
                creationflags=creationflags,
            )
            try:
                if self.timeout_s is None:
                    returncode = int(proc.wait())
                else:
                    try:
                        returncode = int(proc.wait(timeout=float(self.timeout_s)))
                    except subprocess.TimeoutExpired:
                        timed_out = True
                        returncode = 124
                        _force_kill_process_tree(int(proc.pid))
                        try:
                            proc.wait(timeout=15.0)
                        except Exception:
                            pass
            finally:
                if proc.poll() is None:
                    _force_kill_process_tree(int(proc.pid))
                    try:
                        proc.wait(timeout=10.0)
                    except Exception:
                        pass

        dt = float(time.time() - t0)
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace")
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
        if timed_out:
            stderr_text += (
                f"\n[TIMEOUT] FreeGSNKE script exceeded wall-clock limit "
                f"of {self.timeout_s}s (label={label}); process tree killed.\n"
            )
            stderr_path.write_text(stderr_text, encoding="utf-8", errors="replace")

        hint = _detect_import_error(stderr_text)
        evo_hint = _detect_evolutive_timeout_hint(stdout_text, stderr_text)
        if timed_out:
            hint = "freegsnke_script_timeout"
        elif evo_hint:
            hint = evo_hint
        elif int(returncode) == 124 and label == "evolutive":
            # Child os._exit(124) from per-step watchdog without matching text
            # (rare flush race) — still not the global script budget.
            hint = "evolutive_per_step_timeout"
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


def evolutive_partial_history_n(run_dir: Path) -> int:
    """Count successful evolutive history rows (crash-safe incremental CSV).

    Used when a hung nlstepper is hard-killed: prior steps remain useful and
    should not discard an otherwise successful inverse/forward run.
    """
    run_dir = Path(run_dir)
    for rel in (
        "03_reconstruction/evolutive/history.csv",
        "evolutive/history.csv",
    ):
        p = run_dir / rel
        if not p.is_file():
            continue
        try:
            import csv

            with p.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
        except OSError:
            continue
        n = 0
        for row in rows:
            ok = str(row.get("step_ok", "")).strip().lower()
            if ok in {"1", "true", "yes"}:
                n += 1
            elif ok == "" and row.get("Ip") not in (None, "", "nan", "NaN"):
                # Older history without step_ok still counts finite Ip rows.
                try:
                    float(row.get("Ip"))
                    n += 1
                except (TypeError, ValueError):
                    pass
        return n
    return 0


def evolutive_timeout_is_soft(
    *,
    returncode: int,
    timed_out: bool,
    stdout_text: str,
    n_partial: int,
) -> bool:
    """Whether an evolutive failure should not block the shot.

    Soft when:
      - script wall-clock timeout / per-step ``os._exit(124)`` with ≥1 history rows, or
      - IC static GS watchdog fired before history started (measured_pf IC can hang
        inside one freegs4e Jacobian despite ``max_solving_iterations``).
    """
    if not (timed_out or int(returncode) == 124):
        return False
    if int(n_partial) >= 1:
        return True
    blob = stdout_text or ""
    return ("ic_static_gs" in blob) and ("TIMEOUT" in blob)
