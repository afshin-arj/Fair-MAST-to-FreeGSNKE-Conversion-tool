"""ADR-002 forward replay: measured PF + EFIT-derived profiles → FreeGSNKE GS.

Pentland-style compare (arXiv:2407.12432 spirit): drive FreeGSNKE forward at the
EFIT compare time with plant coil currents (FAIR-MAST ``pf_active`` via coil_map)
and ConstrainPaxisIp knobs from ``profile_trajectory`` (EFIT++ archive fit), then
score that LCFS/shape against the archived EFIT++ solve.

Never invents currents, Ip, or profile coefficients. Soft-skips when authorities
or FreeGSNKE are unavailable unless the compare authority requires otherwise.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

DEFAULT_CIRCUITS = ("P2_inner", "P2_outer", "P3", "P4", "P5", "P6", "Solenoid")


class ForwardReplayError(ValueError):
    pass


def _interp_col(df: pd.DataFrame, t: float, col: str) -> float:
    tt = df["time"].to_numpy(dtype=float)
    yy = df[col].to_numpy(dtype=float)
    m = np.isfinite(tt) & np.isfinite(yy)
    if int(m.sum()) < 1:
        raise ForwardReplayError(f"no finite samples for column {col!r}")
    tt, yy = tt[m], yy[m]
    order = np.argsort(tt)
    tt, yy = tt[order], yy[order]
    if float(t) < float(tt[0]) - 1e-9 or float(t) > float(tt[-1]) + 1e-9:
        raise ForwardReplayError(
            f"t={t} outside {col} coverage [{tt[0]}, {tt[-1]}]"
        )
    return float(np.interp(float(t), tt, yy))


def load_measured_pf_at_time(
    run_dir: Path,
    t_s: float,
    *,
    circuits: Sequence[str] = DEFAULT_CIRCUITS,
) -> Dict[str, float]:
    """Plant PF currents at ``t_s`` from ``inputs/pf_currents.csv`` (coil_map product)."""
    run_dir = Path(run_dir)
    path = None
    for rel in ("inputs/pf_currents.csv", "02_measured_data/02_pf/pf_currents.csv"):
        cand = run_dir / rel
        if cand.is_file():
            path = cand
            break
    if path is None:
        raise ForwardReplayError(
            "forward_replay requires inputs/pf_currents.csv "
            "(measured pf_active via coil_map) — never invent coil currents"
        )
    df = pd.read_csv(path)
    if "time" not in df.columns:
        raise ForwardReplayError("pf_currents.csv missing time column")
    out: Dict[str, float] = {}
    missing: List[str] = []
    for c in circuits:
        if c not in df.columns or not np.isfinite(df[c]).any():
            missing.append(c)
            continue
        out[str(c)] = _interp_col(df, float(t_s), str(c))
    if missing:
        raise ForwardReplayError(
            "PF currents missing/non-finite for circuits: "
            + ", ".join(missing)
            + " (no silent 0 A)"
        )
    return out


def load_measured_ip_at_time(run_dir: Path, t_s: float) -> float:
    from .planner_picard import interp_ip, load_ip_series

    for rel in ("inputs", ""):
        base = Path(run_dir) / rel if rel else Path(run_dir)
        if (base / "ip.csv").is_file():
            return interp_ip(float(t_s), *load_ip_series(base))
    for rel in ("02_measured_data/01_magnetics",):
        p = Path(run_dir) / rel / "ip.csv"
        if p.is_file():
            return interp_ip(float(t_s), *load_ip_series(p.parent))
    raise ForwardReplayError(
        "forward_replay requires measured ip.csv — never invent Ip"
    )


def resolve_forward_replay_profiles(run_dir: Path, t_s: float) -> Dict[str, Any]:
    """Prefer EFIT-derived profile_trajectory; fail if only held IC (not Pentland)."""
    from .planner_picard import resolve_profile_knobs

    inputs = Path(run_dir) / "inputs"
    if not inputs.is_dir():
        inputs = Path(run_dir)
    knobs = resolve_profile_knobs(inputs_dir=inputs, t_s=float(t_s))
    if knobs.get("source") != "profile_trajectory":
        raise ForwardReplayError(
            "forward_replay requires inputs/profile_trajectory_authority/"
            "profile_trajectory.json with status=ok (ADR-004 EFIT++ fit). "
            f"Got source={knobs.get('source')!r} — refusing execution_authority hold "
            "as a fake Pentland compare."
        )
    return knobs


def run_efit_forward_replay(
    *,
    run_dir: Path,
    t_s: float,
    machine_dir: Path,
    freegsnke_python: Optional[str] = None,
    repo_root: Optional[Path] = None,
    circuits: Sequence[str] = DEFAULT_CIRCUITS,
    solve_gs_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Forward GS at ``t_s``; persist LCFS/shape under ``04_efit_compare/forward_replay/``."""
    from .freegsnke_lcfs import lcfs_arrays_from_eq, persist_lcfs_from_eq, write_freegsnke_lcfs_csv
    from .planner_picard import load_grid_and_solver, solve_forward_gs_at_currents
    from .shape_scorecard import extract_freegsnke_shape_targets, shape_from_lcfs_polyline

    run_dir = Path(run_dir)
    machine_dir = Path(machine_dir)
    out = Path(out_dir) if out_dir is not None else (
        run_dir / "04_efit_compare" / "forward_replay"
    )
    out.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {
        "ok": False,
        "status": "failed",
        "t_s": float(t_s),
        "compare_mode": "forward_replay",
        "current_source": "measured_pf_at_compare_time",
        "profile_source": None,
        "notes": [],
        "errors": [],
        "files": [],
    }

    try:
        currents = load_measured_pf_at_time(run_dir, float(t_s), circuits=circuits)
        Ip = load_measured_ip_at_time(run_dir, float(t_s))
        knobs = resolve_forward_replay_profiles(run_dir, float(t_s))
        report["profile_source"] = knobs.get("source")
        report["profile_knobs"] = {
            k: float(knobs[k]) for k in ("paxis", "fvac", "alpha_m", "alpha_n")
        }
        report["Ip_A"] = float(Ip)
        report["coil_currents_A"] = {k: float(v) for k, v in currents.items()}
    except Exception as e:
        report["errors"].append(f"{type(e).__name__}:{e}")
        report["status"] = "skipped_insufficient_inputs"
        (out / "FORWARD_REPLAY.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        report["files"].append(str((out / "FORWARD_REPLAY.json").as_posix()))
        return report

    inputs = run_dir / "inputs"
    if not (inputs / "execution_authority" / "execution_authority_bundle.json").is_file():
        for cand in (run_dir / "inputs", run_dir):
            if (cand / "execution_authority" / "execution_authority_bundle.json").is_file():
                inputs = cand
                break
    try:
        grid, solv = load_grid_and_solver(inputs)
    except Exception as e:
        report["errors"].append(f"grid_solver:{type(e).__name__}:{e}")
        report["status"] = "skipped_missing_execution_authority"
        (out / "FORWARD_REPLAY.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        return report

    solve = solve_gs_fn or solve_forward_gs_at_currents
    try:
        gs = solve(
            machine_dir=machine_dir,
            circuit_order=list(circuits),
            currents_A=currents,
            Ip_A=float(Ip),
            profile_knobs={
                "paxis": float(knobs["paxis"]),
                "fvac": float(knobs["fvac"]),
                "alpha_m": float(knobs["alpha_m"]),
                "alpha_n": float(knobs["alpha_n"]),
            },
            grid=grid,
            solver_spec=solv,
        )
    except Exception as e:
        report["notes"].append(f"in_process_gs_failed:{type(e).__name__}:{e}")
        try:
            gs = _solve_via_freegsnke_venv(
                run_dir=run_dir,
                machine_dir=machine_dir,
                t_s=float(t_s),
                currents=currents,
                Ip=float(Ip),
                knobs=knobs,
                grid=grid,
                solv=solv,
                freegsnke_python=freegsnke_python,
                repo_root=repo_root,
            )
        except Exception as e2:
            report["errors"].append(f"gs_solve_failed:{type(e2).__name__}:{e2}")
            report["status"] = "skipped_freegsnke_unavailable"
            (out / "FORWARD_REPLAY.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            return report

    eq = gs.get("eq")
    if eq is None and gs.get("lcfs_R") is not None:
        rr = np.asarray(gs["lcfs_R"], dtype=float)
        zz = np.asarray(gs["lcfs_Z"], dtype=float)
        shape = shape_from_lcfs_polyline(rr, zz)
        boundary = (rr, zz)
    elif eq is None:
        report["errors"].append("gs_solve_returned_no_eq")
        report["status"] = "failed"
        (out / "FORWARD_REPLAY.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
        return report
    else:
        lc = lcfs_arrays_from_eq(eq)
        if lc is None:
            report["errors"].append("lcfs_extract_failed_after_forward_replay")
            report["status"] = "failed"
            (out / "FORWARD_REPLAY.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            return report
        boundary = lc
        try:
            shape = extract_freegsnke_shape_targets(eq)
        except Exception:
            shape = shape_from_lcfs_polyline(lc[0], lc[1])

    rr, zz = boundary
    lcfs_path = out / "freegsnke_forward_replay_lcfs.csv"
    write_freegsnke_lcfs_csv(lcfs_path, rr, zz, time_s=float(t_s))
    report["files"].append(str(lcfs_path.as_posix()))
    if eq is not None:
        try:
            persist_lcfs_from_eq(out, eq, time_s=float(t_s))
        except Exception as e:
            report["notes"].append(f"persist_lcfs_warn:{type(e).__name__}:{e}")

    dump: Dict[str, Any] = {
        "t0": float(t_s),
        "Ip": float(Ip),
        "coil_currents": {k: float(v) for k, v in currents.items()},
        "profile_kwargs": {
            "paxis": float(knobs["paxis"]),
            "Ip": float(Ip),
            "alpha_m": float(knobs["alpha_m"]),
            "alpha_n": float(knobs["alpha_n"]),
        },
        "fvac": float(knobs["fvac"]),
        "lcfs_R": np.asarray(rr, dtype=float),
        "lcfs_Z": np.asarray(zz, dtype=float),
        "compare_mode": "forward_replay",
        "current_source": "measured_pf_at_compare_time",
        "profile_source": knobs.get("source"),
        "magnetic_axis_r": shape.get("magnetic_axis_r"),
        "magnetic_axis_z": shape.get("magnetic_axis_z"),
        "x_point_r": shape.get("x_point_r"),
        "x_point_z": shape.get("x_point_z"),
        "R_in_m": shape.get("R_in_m"),
        "R_out_m": shape.get("R_out_m"),
    }
    if eq is not None:
        try:
            dump["plasma_psi"] = np.asarray(eq.plasma_psi, dtype=float)
            dump["grid"] = {
                "R": np.asarray(eq.R, dtype=float),
                "Z": np.asarray(eq.Z, dtype=float),
                "nx": int(eq.nx),
                "ny": int(eq.ny),
            }
            _psi = eq.psi() if callable(getattr(eq, "psi", None)) else None
            if _psi is not None:
                dump["total_psi"] = np.asarray(_psi, dtype=float)
        except Exception as e:
            report["notes"].append(f"psi_dump_warn:{type(e).__name__}:{e}")
    elif gs.get("plasma_psi") is not None:
        dump["plasma_psi"] = np.asarray(gs["plasma_psi"], dtype=float)
        if gs.get("grid"):
            dump["grid"] = gs["grid"]
        if gs.get("total_psi") is not None:
            dump["total_psi"] = np.asarray(gs["total_psi"], dtype=float)

    dump_path = out / "forward_replay_dump.pkl"
    with open(dump_path, "wb") as f:
        pickle.dump(dump, f)
    report["files"].append(str(dump_path.as_posix()))

    shape_path = out / "freegsnke_forward_replay_shape.json"
    shape_path.write_text(json.dumps(shape, indent=2) + "\n", encoding="utf-8")
    report["files"].append(str(shape_path.as_posix()))

    report["ok"] = True
    report["status"] = "ok"
    report["converged"] = bool(gs.get("converged", True))
    report["lcfs_n_points"] = int(len(rr))
    report["notes"].append(
        "Pentland-style drive: measured PF currents + ADR-004 profile_trajectory "
        "→ FreeGSNKE forward GS (constrain=None); scored vs FAIR-MAST EFIT++ archive"
    )
    meta_out = {k: v for k, v in report.items() if k not in ("lcfs", "freegsnke_shape")}
    (out / "FORWARD_REPLAY.json").write_text(
        json.dumps(meta_out, indent=2, default=str) + "\n", encoding="utf-8"
    )
    report["files"].append(str((out / "FORWARD_REPLAY.json").as_posix()))
    report["lcfs"] = boundary
    report["freegsnke_shape"] = shape
    return report


def load_forward_replay_products(
    run_dir: Path,
) -> Tuple[
    Optional[Tuple[np.ndarray, np.ndarray]],
    Optional[Dict[str, Any]],
    Optional[Dict[str, Any]],
]:
    """Load persisted forward-replay LCFS/shape if present."""
    from .freegsnke_lcfs import read_lcfs_csv

    root = Path(run_dir) / "04_efit_compare" / "forward_replay"
    meta_path = root / "FORWARD_REPLAY.json"
    meta = None
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = None
    if not isinstance(meta, dict) or not meta.get("ok"):
        return None, None, meta
    boundary = None
    lcfs_path = root / "freegsnke_forward_replay_lcfs.csv"
    if lcfs_path.is_file():
        boundary = read_lcfs_csv(lcfs_path)
    shape = None
    shape_path = root / "freegsnke_forward_replay_shape.json"
    if shape_path.is_file():
        try:
            shape = json.loads(shape_path.read_text(encoding="utf-8"))
        except Exception:
            shape = None
    return boundary, shape if isinstance(shape, dict) else None, meta


def _solve_via_freegsnke_venv(
    *,
    run_dir: Path,
    machine_dir: Path,
    t_s: float,
    currents: Dict[str, float],
    Ip: float,
    knobs: Dict[str, Any],
    grid: Dict[str, Any],
    solv: Dict[str, Any],
    freegsnke_python: Optional[str],
    repo_root: Optional[Path],
) -> Dict[str, Any]:
    """Subprocess FreeGSNKE solve when in-process import fails (Windows happy path)."""
    import os
    import subprocess
    import tempfile

    from .freegsnke_runner import resolve_freegsnke_python

    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[2]
    py = resolve_freegsnke_python(freegsnke_python, root)
    payload = {
        "machine_dir": str(Path(machine_dir).resolve()),
        "currents": {k: float(v) for k, v in currents.items()},
        "Ip": float(Ip),
        "knobs": {
            "paxis": float(knobs["paxis"]),
            "fvac": float(knobs["fvac"]),
            "alpha_m": float(knobs["alpha_m"]),
            "alpha_n": float(knobs["alpha_n"]),
        },
        "grid": grid,
        "solv": solv,
        "t_s": float(t_s),
    }
    with tempfile.TemporaryDirectory(prefix="efit_fwd_") as td:
        pay_path = Path(td) / "payload.json"
        out_path = Path(td) / "result.pkl"
        pay_path.write_text(json.dumps(payload), encoding="utf-8")
        script = f"""
import json, pickle
from pathlib import Path
import numpy as np
from freegsnke import build_machine, equilibrium_update, GSstaticsolver
from freegsnke.jtor_update import ConstrainPaxisIp
from mast_freegsnke.freegsnke_lcfs import lcfs_arrays_from_eq
pay = json.loads(Path({str(pay_path)!r}).read_text(encoding="utf-8"))
md = Path(pay["machine_dir"])
tokamak = build_machine.tokamak(
    active_coils_path=str(md / "active_coils.pickle"),
    passive_coils_path=str(md / "passive_coils.pickle"),
    limiter_path=str(md / "limiter.pickle"),
    wall_path=str(md / "wall.pickle"),
)
curr = pay["currents"]
for name, coil in getattr(tokamak, "coils", []):
    if name in curr and hasattr(coil, "current"):
        coil.current = float(curr[name])
g = pay["grid"]
eq = equilibrium_update.Equilibrium(
    tokamak=tokamak,
    Rmin=float(g["Rmin"]), Rmax=float(g["Rmax"]),
    Zmin=float(g["Zmin"]), Zmax=float(g["Zmax"]),
    nx=int(g["nx"]), ny=int(g["ny"]),
)
k = pay["knobs"]
profiles = ConstrainPaxisIp(
    eq=eq, paxis=float(k["paxis"]), Ip=float(pay["Ip"]),
    fvac=float(k["fvac"]), alpha_m=float(k["alpha_m"]), alpha_n=float(k["alpha_n"]),
)
GS = GSstaticsolver.NKGSsolver(eq)
tol = float(pay["solv"].get("forward_target_relative_tolerance", 1e-6))
maxit = int(pay["solv"].get("max_solving_iterations", 50))
GS.solve(eq=eq, profiles=profiles, constrain=None,
         target_relative_tolerance=tol, max_solving_iterations=maxit, verbose=0)
lc = lcfs_arrays_from_eq(eq)
if lc is None:
    raise SystemExit("lcfs_extract_failed")
rel = float(getattr(GS, "relative_change", float("nan")))
out = {{
    "ok": True,
    "converged": bool(np.isfinite(rel) and rel <= tol),
    "rel_change": rel,
    "lcfs_R": np.asarray(lc[0], dtype=float),
    "lcfs_Z": np.asarray(lc[1], dtype=float),
    "plasma_psi": np.asarray(eq.plasma_psi, dtype=float),
    "grid": {{"R": np.asarray(eq.R, dtype=float), "Z": np.asarray(eq.Z, dtype=float),
             "nx": int(eq.nx), "ny": int(eq.ny)}},
}}
try:
    out["total_psi"] = np.asarray(eq.psi(), dtype=float)
except Exception:
    pass
with open({str(out_path)!r}, "wb") as f:
    pickle.dump(out, f)
print("ok")
"""
        env = dict(os.environ)
        src_path = str((root / "src").resolve())
        prev = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src_path + ((os.pathsep + prev) if prev else "")
        r = subprocess.run(
            [str(py), "-c", script],
            capture_output=True,
            text=True,
            env=env,
            timeout=600.0,
        )
        if r.returncode != 0:
            raise ForwardReplayError(
                f"freegsnke_venv_forward_replay_failed:rc={r.returncode}:"
                f"{(r.stderr or r.stdout or '')[-500:]}"
            )
        with open(out_path, "rb") as f:
            return pickle.load(f)
