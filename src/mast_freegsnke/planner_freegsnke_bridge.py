"""Run planner stage under FreeGSNKE interpreter so isoflux/Picard can import freegsnke.

Pipeline / replan often use a host Python without FreeGSNKE installed; isoflux Green’s
and Picard GS need ``import freegsnke``. Mirror the circuit-dynamics extract pattern:
spawn ``freegsnke_python`` with ``src`` on PYTHONPATH.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .coil_limits import CoilLimitsAuthority, load_coil_limits
from .freegsnke_runner import resolve_freegsnke_python, resolve_repo_src
from .planner import (
    CircuitDynamics,
    PlannerAuthority,
    PlannerError,
    load_circuit_dynamics,
    load_planner_authority,
    run_planner_stage,
    write_circuit_dynamics,
)


class PlannerBridgeError(RuntimeError):
    """Subprocess planner failed (import, crash, or non-zero exit)."""


_RESULT_PREFIX = "MAST_PLANNER_BRIDGE_RESULT:"


def freegsnke_importable() -> bool:
    try:
        import freegsnke  # noqa: F401

        return True
    except Exception:
        return False


def build_planner_job(
    *,
    run_dir: Path,
    inputs_dir: Path,
    machine_dir: Path,
    circuit_order: Sequence[str],
    t_start: float,
    t_end: float,
    shot: Optional[int] = None,
    cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """JSON-serializable job for the FreeGSNKE-python child (paths only)."""
    inputs_dir = Path(inputs_dir)
    return {
        "run_dir": str(Path(run_dir).resolve()),
        "inputs_dir": str(inputs_dir.resolve()),
        "machine_dir": str(Path(machine_dir).resolve()),
        "planner_authority_path": str(
            (inputs_dir / "planner_authority" / "planner_authority.json").resolve()
        ),
        "coil_limits_path": str(
            (inputs_dir / "coil_limits_authority" / "coil_limits_authority.json").resolve()
        ),
        "circuit_dynamics_path": str(
            (inputs_dir / "circuit_dynamics_snapshot.json").resolve()
        ),
        "shape_targets_path": str(
            (inputs_dir / "shape_targets_authority" / "shape_targets.json").resolve()
        ),
        "circuit_order": [str(c) for c in circuit_order],
        "t_start": float(t_start),
        "t_end": float(t_end),
        "shot": int(shot) if shot is not None else None,
        "cache_dir": str(Path(cache_dir).resolve()) if cache_dir is not None else None,
    }


def execute_planner_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Child entry: load authorities from job paths and run ``run_planner_stage``."""
    run_dir = Path(job["run_dir"])
    inputs_dir = Path(job["inputs_dir"])
    machine_dir = Path(job["machine_dir"])
    pl = load_planner_authority(Path(job["planner_authority_path"]))
    cl = load_coil_limits(Path(job["coil_limits_path"]))
    dyn_path = Path(job["circuit_dynamics_path"])
    dyn = load_circuit_dynamics(dyn_path) if dyn_path.is_file() else None
    st = None
    st_path = job.get("shape_targets_path")
    if st_path and Path(st_path).is_file():
        st = json.loads(Path(st_path).read_text(encoding="utf-8"))
    cache = Path(job["cache_dir"]) if job.get("cache_dir") else None
    return run_planner_stage(
        run_dir=run_dir,
        inputs_dir=inputs_dir,
        machine_dir=machine_dir,
        planner_auth=pl,
        coil_limits=cl,
        circuit_order=list(job["circuit_order"]),
        t_start=float(job["t_start"]),
        t_end=float(job["t_end"]),
        shot=job.get("shot"),
        circuit_dynamics=dyn,
        shape_targets=st if isinstance(st, dict) else None,
        cache_dir=cache,
    )


def _parse_result_line(stdout: str) -> Optional[Dict[str, Any]]:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if line.startswith(_RESULT_PREFIX):
            return json.loads(line[len(_RESULT_PREFIX) :])
    return None


def run_planner_stage_via_freegsnke_python(
    *,
    run_dir: Path,
    inputs_dir: Path,
    machine_dir: Path,
    planner_auth: PlannerAuthority,
    coil_limits: CoilLimitsAuthority,
    circuit_order: Sequence[str],
    t_start: float,
    t_end: float,
    freegsnke_python: str,
    repo_root: Path,
    shot: Optional[int] = None,
    circuit_dynamics: Optional[CircuitDynamics] = None,
    shape_targets: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[Path] = None,
    timeout_s: Optional[float] = 1200.0,
) -> Dict[str, Any]:
    """Spawn FreeGSNKE python to run the full planner stage (isoflux + Picard + QP)."""
    run_dir = Path(run_dir)
    inputs_dir = Path(inputs_dir)
    # Ensure snapshots exist for the child (authorities already on disk in pipeline).
    pl_path = inputs_dir / "planner_authority" / "planner_authority.json"
    cl_path = inputs_dir / "coil_limits_authority" / "coil_limits_authority.json"
    if not pl_path.is_file():
        pl_path.parent.mkdir(parents=True, exist_ok=True)
        pl_path.write_text(
            json.dumps(planner_auth.to_json_dict(), indent=2) + "\n", encoding="utf-8"
        )
    if not cl_path.is_file():
        from .coil_limits import write_coil_limits

        write_coil_limits(inputs_dir, coil_limits)
    if circuit_dynamics is not None:
        write_circuit_dynamics(inputs_dir / "circuit_dynamics_snapshot.json", circuit_dynamics)
    if isinstance(shape_targets, dict):
        st_dir = inputs_dir / "shape_targets_authority"
        st_dir.mkdir(parents=True, exist_ok=True)
        (st_dir / "shape_targets.json").write_text(
            json.dumps(shape_targets, indent=2) + "\n", encoding="utf-8"
        )

    job = build_planner_job(
        run_dir=run_dir,
        inputs_dir=inputs_dir,
        machine_dir=machine_dir,
        circuit_order=circuit_order,
        t_start=t_start,
        t_end=t_end,
        shot=shot,
        cache_dir=cache_dir,
    )
    job_path = run_dir / "07_planner" / "_planner_bridge_job.json"
    job_path.parent.mkdir(parents=True, exist_ok=True)
    job_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")

    py = resolve_freegsnke_python(freegsnke_python, repo_root=repo_root)
    if not Path(py).exists():
        raise PlannerBridgeError(f"freegsnke_python not found: {py}")

    job_lit = json.dumps(str(job_path.resolve()))
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from mast_freegsnke.planner_freegsnke_bridge import execute_planner_job, _RESULT_PREFIX\n"
        f"job=json.loads(Path(json.loads({job_lit!r})).read_text(encoding='utf-8'))\n"
        "try:\n"
        "    out=execute_planner_job(job)\n"
        "except Exception as e:\n"
        "    print(_RESULT_PREFIX + json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'}))\n"
        "    raise\n"
        "summary={k: out.get(k) for k in ("
        "'ok','status','path','n_knots','residual_rms_mean_V',"
        "'residual_rms_mean_measured_V','n_voltage_violations_raw',"
        "'residual_rms_by_circuit')}\n"
        "meta=out.get('meta') or {}\n"
        "summary['isoflux_cost']=meta.get('isoflux_cost')\n"
        "summary['isoflux_status']=meta.get('isoflux_status')\n"
        "summary['picard']=meta.get('picard')\n"
        "summary['picard_status']=meta.get('picard_status')\n"
        "print(_RESULT_PREFIX + json.dumps(summary))\n"
    )

    env = dict(os.environ)
    env.setdefault("PYTHONUNBUFFERED", "1")
    src = resolve_repo_src(repo_root)
    if src is not None:
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(src.resolve()) + ((os.pathsep + prev) if prev else "")

    r = subprocess.run(
        [str(py), "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=float(timeout_s) if timeout_s is not None else None,
        cwd=str(Path(repo_root).resolve()),
    )
    log_dir = run_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "planner_bridge.stdout.txt").write_text(r.stdout or "", encoding="utf-8")
    (log_dir / "planner_bridge.stderr.txt").write_text(r.stderr or "", encoding="utf-8")

    parsed = _parse_result_line(r.stdout or "")
    if r.returncode != 0:
        err = (parsed or {}).get("error") if isinstance(parsed, dict) else None
        raise PlannerBridgeError(
            err
            or f"planner bridge exit={r.returncode}: {(r.stderr or '')[-800:]}"
        )
    if not isinstance(parsed, dict) or not parsed.get("ok"):
        raise PlannerBridgeError(
            (parsed or {}).get("error")
            if isinstance(parsed, dict)
            else "planner bridge missing result line"
        )

    # Artifacts already on disk; rebuild return dict from PLANNER.json for callers.
    plan_json = Path(run_dir) / "07_planner" / "PLANNER.json"
    meta = {}
    if plan_json.is_file():
        meta = json.loads(plan_json.read_text(encoding="utf-8"))
    return {
        "ok": True,
        "status": parsed.get("status") or meta.get("status"),
        "path": parsed.get("path") or str(Path(run_dir) / "07_planner"),
        "n_knots": parsed.get("n_knots") or meta.get("n_knots"),
        "residual_rms_by_circuit": parsed.get("residual_rms_by_circuit")
        or meta.get("residual_rms_by_circuit"),
        "residual_rms_mean_V": parsed.get("residual_rms_mean_V")
        or meta.get("residual_rms_mean_V"),
        "residual_rms_mean_measured_V": parsed.get("residual_rms_mean_measured_V")
        or meta.get("residual_rms_mean_measured_V"),
        "mean_i_track_rms_A": meta.get("mean_i_track_rms_A"),
        "mean_rms_plan_minus_dyn_V": meta.get("mean_rms_plan_minus_dyn_V"),
        "voltage_model_gap_overall": meta.get("voltage_model_gap_overall"),
        "n_voltage_violations_raw": parsed.get("n_voltage_violations_raw")
        or meta.get("n_voltage_violations_raw"),
        "meta": meta,
        "bridge": {
            "python_exe": py,
            "job_path": str(job_path),
            "isoflux_cost": parsed.get("isoflux_cost", meta.get("isoflux_cost")),
            "isoflux_status": parsed.get("isoflux_status", meta.get("isoflux_status")),
            "picard": parsed.get("picard", meta.get("picard")),
            "picard_status": parsed.get("picard_status", meta.get("picard_status")),
        },
    }


def run_planner_stage_prefer_freegsnke(
    *,
    run_dir: Path,
    inputs_dir: Path,
    machine_dir: Path,
    planner_auth: PlannerAuthority,
    coil_limits: CoilLimitsAuthority,
    circuit_order: Sequence[str],
    t_start: float,
    t_end: float,
    freegsnke_python: Optional[str] = None,
    repo_root: Optional[Path] = None,
    shot: Optional[int] = None,
    circuit_dynamics: Optional[CircuitDynamics] = None,
    shape_targets: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[Path] = None,
    timeout_s: Optional[float] = 1200.0,
) -> Dict[str, Any]:
    """Prefer FreeGSNKE python when configured; fall back to in-process on bridge failure.

    Soft-skip isoflux/Picard remains available on in-process fallback unless
    ``require_isoflux`` / ``require_picard`` (then raise).
    """
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    configured = bool(freegsnke_python and str(freegsnke_python).strip())
    use_bridge = configured
    # Fast path: host already has freegsnke and is the configured interpreter.
    if configured and freegsnke_importable():
        resolved = resolve_freegsnke_python(freegsnke_python, repo_root=root)
        if Path(resolved).resolve() == Path(sys.executable).resolve():
            use_bridge = False
    # Host lacks freegsnke → must bridge when freegsnke_python is configured.
    elif configured and not freegsnke_importable():
        use_bridge = True

    if use_bridge:
        try:
            return run_planner_stage_via_freegsnke_python(
                run_dir=run_dir,
                inputs_dir=inputs_dir,
                machine_dir=machine_dir,
                planner_auth=planner_auth,
                coil_limits=coil_limits,
                circuit_order=circuit_order,
                t_start=t_start,
                t_end=t_end,
                freegsnke_python=str(freegsnke_python),
                repo_root=root,
                shot=shot,
                circuit_dynamics=circuit_dynamics,
                shape_targets=shape_targets,
                cache_dir=cache_dir,
                timeout_s=timeout_s,
            )
        except Exception as e:
            if planner_auth.require_isoflux or planner_auth.require_picard:
                raise PlannerError(
                    f"planner FreeGSNKE bridge failed and require_isoflux/picard=true: "
                    f"{type(e).__name__}: {e}"
                ) from e
            # Soft fallback: in-process QP; isoflux soft-skips without freegsnke.
            out = run_planner_stage(
                run_dir=run_dir,
                inputs_dir=inputs_dir,
                machine_dir=machine_dir,
                planner_auth=planner_auth,
                coil_limits=coil_limits,
                circuit_order=circuit_order,
                t_start=t_start,
                t_end=t_end,
                shot=shot,
                circuit_dynamics=circuit_dynamics,
                shape_targets=shape_targets,
                cache_dir=cache_dir,
            )
            meta = out.get("meta") or {}
            meta["planner_bridge_fallback"] = (
                f"{type(e).__name__}: {e}"
            )
            out["meta"] = meta
            out["bridge_fallback"] = str(e)
            plan_json = Path(run_dir) / "07_planner" / "PLANNER.json"
            if plan_json.is_file() and isinstance(meta, dict):
                try:
                    disk = json.loads(plan_json.read_text(encoding="utf-8"))
                    disk["planner_bridge_fallback"] = meta["planner_bridge_fallback"]
                    plan_json.write_text(
                        json.dumps(disk, indent=2) + "\n", encoding="utf-8"
                    )
                except Exception:
                    pass
            return out

    return run_planner_stage(
        run_dir=run_dir,
        inputs_dir=inputs_dir,
        machine_dir=machine_dir,
        planner_auth=planner_auth,
        coil_limits=coil_limits,
        circuit_order=circuit_order,
        t_start=t_start,
        t_end=t_end,
        shot=shot,
        circuit_dynamics=circuit_dynamics,
        shape_targets=shape_targets,
        cache_dir=cache_dir,
    )
