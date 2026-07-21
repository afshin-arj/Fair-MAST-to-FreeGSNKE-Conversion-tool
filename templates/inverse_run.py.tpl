# --- Auto-injected window support (v0.6.0) ---
import json
from pathlib import Path

def _load_window():
    wp = Path(__file__).resolve().parent / "inputs" / "window.json"
    if not wp.exists():
        return None
    try:
        obj = json.loads(wp.read_text())
        if isinstance(obj, dict) and "t_start" in obj and "t_end" in obj:
            return float(obj["t_start"]), float(obj["t_end"])
    except Exception:
        return None
    return None

_tw = _load_window()
T_START = _tw[0] if _tw is not None else None
T_END = _tw[1] if _tw is not None else None

if _tw is None:
    print("[WARN] inputs/window.json missing or invalid. Inverse run will use template defaults.")
else:
    print(f"[OK] Using inferred time window: {T_START} .. {T_END}")

# NOTE:
# Wire T_START/T_END into your FreeGSNKE inverse solver call (e.g., selecting a time slice or time-range).
# -----------------------------------------------

import json
from pathlib import Path

def _load_window():
    wp = Path(__file__).resolve().parent / "inputs" / "window.json"
    if wp.exists():
        try:
            obj = json.loads(wp.read_text())
            if isinstance(obj, dict) and "t_start" in obj and "t_end" in obj:
                return float(obj["t_start"]), float(obj["t_end"])
        except Exception:
            return None
    return None

_tw = _load_window()
T_WINDOW = _tw


def _load_execution_authority_bundle() -> dict:
    """Load inputs/execution_authority/execution_authority_bundle.json.

    Fail-fast: this run is execution-authoritative; no hidden defaults.
    """
    bp = Path(__file__).resolve().parent / "inputs" / "execution_authority" / "execution_authority_bundle.json"
    if not bp.exists():
        raise FileNotFoundError("Missing execution authority bundle: " + str(bp))
    obj = json.loads(bp.read_text())
    if not isinstance(obj, dict):
        raise ValueError("Execution authority bundle must be a JSON object")
    for k in ["grid", "profile", "profile_basis", "boundary", "solver"]:
        if k not in obj:
            raise KeyError("Execution authority bundle missing key: " + str(k))
    return obj

#!/usr/bin/env python3
# Generated FreeGSNKE diverted inverse solve (shape/topology first)
#
# Author: © 2026 Afshin Arjhangmehr

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import time as _time
import multiprocessing as _mp

from freegsnke import build_machine
from freegsnke import equilibrium_update
from freegsnke.jtor_update import ConstrainPaxisIp
from freegsnke import GSstaticsolver
from freegsnke.inverse import Inverse_optimizer

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
MACHINE = Path(__MACHINE_DIR_REPR__)

def choose_formed_plasma_time(ip_df: pd.DataFrame, frac: float = __FORMED_FRAC__):
    t = ip_df["time"].to_numpy(dtype=float)
    ip = ip_df["ip"].to_numpy(dtype=float)
    mask_pos = ip > 0
    t = t[mask_pos]; ip = ip[mask_pos]
    ip_max = float(np.max(ip))
    mask = ip >= frac * ip_max
    if not np.any(mask):
        raise RuntimeError("Could not find formed plasma time. Lower formed_plasma_frac.")
    t_sel = t[mask]; ip_sel = ip[mask]
    dip_dt = np.gradient(ip_sel, t_sel)
    idx = int(np.argmin(np.abs(dip_dt)))
    return float(t_sel[idx]), float(ip_sel[idx]), ip_max

def interp_at_time(df, t0, value_col):
    t = df["time"].to_numpy(dtype=float)
    y = df[value_col].to_numpy(dtype=float)
    order = np.argsort(t)
    return float(np.interp(t0, t[order], y[order]))

def load_pf_currents(t0: float) -> dict:
    path = INPUTS / "pf_currents.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Provide coil_map_path in config so the pipeline can apply_coil_map."
        )
    df = pd.read_csv(path)
    out = {}
    missing = []
    for c in ["P2_inner","P2_outer","P3","P4","P5","P6","Solenoid"]:
        if c in df.columns and np.isfinite(df[c]).any():
            out[c] = interp_at_time(df, t0, c)
        else:
            missing.append(c)
    if missing:
        raise RuntimeError(
            "PF currents missing/non-finite for circuits: "
            + ", ".join(missing)
            + ". Fix coil_map authority (no silent 0.0 A defaults)."
        )
    return out

def compute_sample_times(ea: dict):
    """Deterministic window sample times for multi-time synthetic diagnostics.

    Governed by the metrics_timebase execution authority (v10.4.0):
      rule 'linspace_window_inclusive' -> n_times equally spaced samples in
      the finalized window [t_start, t_end], endpoints included.
    Fail-fast: no window / no authority means no synthetic timebase.
    """
    mt = ea.get("metrics_timebase")
    if not isinstance(mt, dict):
        raise KeyError(
            "Execution authority bundle missing 'metrics_timebase' "
            "(required for multi-time synthetic diagnostics)"
        )
    rule = str(mt["rule"])
    n = int(mt["n_times"])
    if rule != "linspace_window_inclusive":
        raise ValueError(f"Unsupported metrics_timebase rule: {rule}")
    if T_WINDOW is None:
        raise RuntimeError(
            "inputs/window.json missing or invalid: multi-time synthetic diagnostics "
            "require the finalized time window."
        )
    t_start, t_end = float(T_WINDOW[0]), float(T_WINDOW[1])
    times = [float(x) for x in np.linspace(t_start, t_end, n)]
    meta = {"rule": rule, "n_times": n, "t_start": t_start, "t_end": t_end}
    return times, meta


def _load_multitime_spec(solv: dict) -> dict:
    """Load solver.multitime authority with fail-closed defaults (v10.5.0)."""
    mt = solv.get("multitime")
    if not isinstance(mt, dict):
        raise KeyError(
            "Execution authority solver.multitime missing "
            "(required for multi-time synthetic diagnostics, v10.5.0)"
        )
    preferred = str(mt.get("preferred_mode", "full_inverse"))
    fallback = str(mt.get("fallback_mode", "forward_gs"))
    fresh = bool(mt.get("fresh_constrain_per_time", True))
    if not fresh:
        raise ValueError(
            "solver.multitime.fresh_constrain_per_time must be True: "
            "reusing Inverse_optimizer across times stalls under FreeGSNKE 3.0.1 "
            "(uncapped residual-resize loop in GSstaticsolver.forward_solve / "
            "freegs4e.critical.fastcrit)."
        )
    if preferred not in {"full_inverse", "forward_gs"}:
        raise ValueError(f"unsupported preferred_mode: {preferred}")
    if fallback not in {"forward_gs", "skip"}:
        raise ValueError(f"unsupported fallback_mode: {fallback}")
    return {
        "preferred_mode": preferred,
        "fallback_mode": fallback,
        "max_solving_iterations": int(mt.get("max_solving_iterations", 50)),
        "per_time_timeout_s": float(mt.get("per_time_timeout_s", 180.0)),
        "continuation": bool(mt.get("continuation", True)),
        "fresh_constrain_per_time": True,
    }


def _solve_one_sample_inplace(
    *,
    eq,
    solver,
    tokamak,
    profiles_kwargs: dict,
    solv: dict,
    mt_spec: dict,
    bnd: dict,
    t_i: float,
    ip_i: float,
    pf_i: dict,
    mode: str,
    l2_reg,
):
    """In-process inverse or forward_gs solve at one sample time.

    Prefer ``_solve_one_sample`` (hard per-time kill). Soft post-hoc timing
    cannot interrupt a hung FreeGSNKE ``solver.solve``.
    """
    set_machine_currents(tokamak, pf_i)
    profiles_i = ConstrainPaxisIp(eq=eq, Ip=float(ip_i), **profiles_kwargs)
    tic = _time.time()
    try:
        if mode == "full_inverse":
            constrain = Inverse_optimizer(
                null_points=bnd["null_points"],
                isoflux_set=np.array(bnd["isoflux_set"], dtype=float),
            )
            solver.solve(
                eq=eq,
                profiles=profiles_i,
                constrain=constrain,
                target_relative_tolerance=float(solv["inverse_target_relative_tolerance"]),
                target_relative_psit_update=float(solv["inverse_target_relative_psit_update"]),
                max_solving_iterations=int(mt_spec["max_solving_iterations"]),
                l2_reg=l2_reg,
                verbose=False,
            )
            rel = float(getattr(solver, "relative_change", float("nan")))
            iters = int(len(getattr(solver, "constrain_loss", [])))
            tol = float(solv["inverse_target_relative_tolerance"])
            duration_s = float(_time.time() - tic)
            if duration_s > float(mt_spec["per_time_timeout_s"]):
                return {
                    "ok": False,
                    "status": "timeout",
                    "solve_mode": mode,
                    "iterations": iters,
                    "rel_change": rel,
                    "duration_s": duration_s,
                    "error": (
                        f"per-time solve exceeded solver.multitime.per_time_timeout_s="
                        f"{mt_spec['per_time_timeout_s']}s (soft wall-clock)"
                    ),
                }
            if not (np.isfinite(rel) and rel <= tol):
                return {
                    "ok": False,
                    "status": "not_converged",
                    "solve_mode": mode,
                    "iterations": iters,
                    "rel_change": rel,
                    "duration_s": duration_s,
                    "error": (
                        f"inverse did not reach tolerance: rel_change={rel:.3e} vs {tol:.3e} "
                        f"in {iters}/{int(mt_spec['max_solving_iterations'])} iterations"
                    ),
                }
            return {
                "ok": True,
                "status": "converged",
                "solve_mode": mode,
                "iterations": iters,
                "rel_change": rel,
                "duration_s": duration_s,
                "error": None,
            }
        if mode == "forward_gs":
            solver.solve(
                eq=eq,
                profiles=profiles_i,
                constrain=None,
                target_relative_tolerance=float(solv["forward_target_relative_tolerance"]),
                max_solving_iterations=int(mt_spec["max_solving_iterations"]),
                verbose=False,
            )
            rel = float(getattr(solver, "relative_change", float("nan")))
            iters = int(max(0, len(getattr(solver, "norm_rel_change", [])) - 1))
            duration_s = float(_time.time() - tic)
            tol = float(solv["forward_target_relative_tolerance"])
            if duration_s > float(mt_spec["per_time_timeout_s"]):
                return {
                    "ok": False,
                    "status": "timeout",
                    "solve_mode": mode,
                    "iterations": iters,
                    "rel_change": rel,
                    "duration_s": duration_s,
                    "error": (
                        f"per-time solve exceeded solver.multitime.per_time_timeout_s="
                        f"{mt_spec['per_time_timeout_s']}s (soft wall-clock)"
                    ),
                }
            status = "converged" if (np.isfinite(rel) and rel <= tol) else "completed_max_iter"
            err = None
            if status != "converged":
                err = (
                    f"forward_gs finished without meeting tolerance: "
                    f"rel_change={rel:.3e} vs {tol:.3e} in {iters} iterations"
                )
            return {
                "ok": True,
                "status": status,
                "solve_mode": mode,
                "iterations": iters,
                "rel_change": rel,
                "duration_s": duration_s,
                "error": err,
            }
        raise ValueError(f"unknown solve_mode: {mode}")
    except Exception as e:
        return {
            "ok": False,
            "status": "error",
            "solve_mode": mode,
            "iterations": 0,
            "rel_change": None,
            "duration_s": float(_time.time() - tic),
            "error": f"{type(e).__name__}: {e}",
        }


def _multitime_solve_worker(payload: dict) -> None:
    """Spawn-child entry for one multi-time sample (hard per_time_timeout_s kill).

    Loads a pickled tokamak (~0.05s) and rebuilds Equilibrium so a hung
    FreeGSNKE residual-resize loop can be terminated without killing the
    whole inverse script.
    """
    import pickle as _pickle

    tokamak = _pickle.loads(Path(payload["tokamak_pickle"]).read_bytes())
    grid = payload["grid"]
    eq = equilibrium_update.Equilibrium(
        tokamak=tokamak,
        Rmin=float(grid["Rmin"]), Rmax=float(grid["Rmax"]),
        Zmin=float(grid["Zmin"]), Zmax=float(grid["Zmax"]),
        nx=int(grid["nx"]), ny=int(grid["ny"]),
    )
    psi = np.load(payload["plasma_psi_in"])
    eq.plasma_psi = np.array(psi, dtype=float, copy=True)
    eq.solved = False
    solver = GSstaticsolver.NKGSsolver(eq)
    result = _solve_one_sample_inplace(
        eq=eq,
        solver=solver,
        tokamak=tokamak,
        profiles_kwargs=payload["profiles_kwargs"],
        solv=payload["solv"],
        mt_spec=payload["mt_spec"],
        bnd=payload["bnd"],
        t_i=float(payload["t_i"]),
        ip_i=float(payload["ip_i"]),
        pf_i=payload["pf_i"],
        mode=str(payload["mode"]),
        l2_reg=np.array(payload["l2_reg"], dtype=float),
    )
    if result.get("ok"):
        np.save(payload["plasma_psi_out"], np.asarray(eq.plasma_psi, dtype=float))
    Path(payload["result_json"]).write_text(json.dumps(result) + "\n", encoding="utf-8")


def _solve_one_sample(
    *,
    eq,
    solver,
    tokamak,
    profiles_kwargs: dict,
    solv: dict,
    mt_spec: dict,
    bnd: dict,
    grid: dict,
    t_i: float,
    ip_i: float,
    pf_i: dict,
    mode: str,
    l2_reg,
    tokamak_pickle: Path,
):
    """Solve one window sample with a hard wall-clock kill (multiprocessing).

    FreeGSNKE 3.0.1 can hang forever inside an uncapped residual-resize loop;
    soft post-hoc timing cannot escape that. A spawn child is terminated when
    ``per_time_timeout_s`` elapses so fallback_mode can still run.
    """
    import pickle as _pickle

    work = HERE / ".multitime_work"
    work.mkdir(parents=True, exist_ok=True)
    if not tokamak_pickle.exists():
        tokamak_pickle.write_bytes(_pickle.dumps(tokamak, protocol=5))

    tag = f"{mode}_{t_i:.6f}".replace(".", "p")
    psi_in = work / f"{tag}_psi_in.npy"
    psi_out = work / f"{tag}_psi_out.npy"
    result_json = work / f"{tag}_result.json"
    for pth in (psi_out, result_json):
        if pth.exists():
            pth.unlink()
    np.save(psi_in, np.asarray(eq.plasma_psi, dtype=float))

    payload = {
        "tokamak_pickle": str(tokamak_pickle),
        "grid": grid,
        "profiles_kwargs": profiles_kwargs,
        "solv": solv,
        "mt_spec": mt_spec,
        "bnd": bnd,
        "t_i": float(t_i),
        "ip_i": float(ip_i),
        "pf_i": {k: float(v) for k, v in pf_i.items()},
        "mode": mode,
        "l2_reg": [float(x) for x in np.asarray(l2_reg, dtype=float).ravel()],
        "plasma_psi_in": str(psi_in),
        "plasma_psi_out": str(psi_out),
        "result_json": str(result_json),
    }

    ctx = _mp.get_context("spawn")
    proc = ctx.Process(target=_multitime_solve_worker, args=(payload,))
    tic = _time.time()
    proc.start()
    proc.join(timeout=float(mt_spec["per_time_timeout_s"]))
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=5.0)
        return {
            "ok": False,
            "status": "timeout",
            "solve_mode": mode,
            "iterations": None,
            "rel_change": None,
            "duration_s": float(_time.time() - tic),
            "error": (
                f"hard kill: per-time solve exceeded solver.multitime.per_time_timeout_s="
                f"{mt_spec['per_time_timeout_s']}s (child process terminated)"
            ),
        }

    if not result_json.exists():
        return {
            "ok": False,
            "status": "error",
            "solve_mode": mode,
            "iterations": None,
            "rel_change": None,
            "duration_s": float(_time.time() - tic),
            "error": f"child exited without result (exitcode={proc.exitcode})",
        }
    result = json.loads(result_json.read_text(encoding="utf-8"))
    if result.get("ok") and psi_out.exists():
        eq.plasma_psi = np.load(psi_out)
        eq.solved = True
        set_machine_currents(tokamak, pf_i)
    return result


def write_synthetic_probe_csvs(tokamak, eq, profiles_kwargs, solver, solv, ea, ip_df, t0: float) -> None:
    """Emit multi-time synthetic diagnostics (v10.5.0).

    Preferred path (solver.multitime.preferred_mode=full_inverse): for EACH
    deterministic window sample time t_i, run a full FreeGSNKE inverse
    (shape/profile optimisation) in-process with:
      - PF currents + Ip interpolated at t_i (measured)
      - a FRESH Inverse_optimizer (required; reuse stalls under FreeGSNKE 3.0.1)
      - sample-to-sample continuation of plasma_psi (not seeded from t0 inverse)
      - max_solving_iterations + per_time_timeout_s from execution authority

    Hard hang protection for the pipeline is FreeGSNKERunner's
    freegsnke_script_timeout_s. On inverse failure/timeout, fallback_mode
    selects forward_gs or skip (never fabricate values).

    Output:
      synthetic/synthetic_fluxloops.csv
      synthetic/synthetic_pickups.csv
      synthetic/synthetic_times.json  (per-time solve status + mode)
    """
    probes = getattr(tokamak, "probes", None)
    if probes is None or not hasattr(probes, "floops"):
        raise RuntimeError(
            "Magnetic probes were not loaded into the tokamak (magnetic_probes.pickle missing?); "
            "cannot emit synthetic diagnostics required by contract metrics."
        )
    probes.initialise_setup(eq)
    fl_names = [str(n) for n in probes.floop_order]
    pu_names = [str(n) for n in probes.pickup_order]

    times, tb_meta = compute_sample_times(ea)
    mt_spec = _load_multitime_spec(solv)
    bnd = ea["boundary"]

    control_names = get_control_coil_names(eq.tokamak)
    l2 = solv.get("l2_reg", {})
    l2_reg = np.array([float(l2.get("default", 0.0))] * len(control_names), dtype=float)
    for cname, val in dict(l2.get("per_coil_override", {})).items():
        if cname in control_names:
            l2_reg[control_names.index(cname)] = float(val)

    fl_rows = []
    pu_rows = []
    per_time = []
    n_inverse = 0
    n_forward = 0
    n_skipped = 0
    # After the t0 inverse, eq holds optimised coil currents + plasma_psi.
    # Pairing that psi with a different time's measured PF re-enters the
    # FreeGSNKE residual-resize stall. Cold-start the multi-time loop; then
    # sample-to-sample continuation keeps measured-PF-consistent solutions.
    eq.plasma_psi = eq.create_psi_plasma_default(adaptive_centre=True)
    eq.solved = False

    for t_i in times:
        pf_i = load_pf_currents(t_i)
        ip_i = interp_at_time(ip_df, t_i, "ip")
        if not mt_spec["continuation"]:
            eq.plasma_psi = eq.create_psi_plasma_default(adaptive_centre=True)
            eq.solved = False

        modes_to_try = [mt_spec["preferred_mode"]]
        if mt_spec["fallback_mode"] == "forward_gs" and mt_spec["preferred_mode"] != "forward_gs":
            modes_to_try.append("forward_gs")

        attempted = []
        result = None
        for mode in modes_to_try:
            print(
                f"[..] window sample {mode}: t={t_i:.6f}s Ip={ip_i/1e6:.3f} MA "
                f"(timeout={mt_spec['per_time_timeout_s']}s, "
                f"max_iter={mt_spec['max_solving_iterations']})",
                flush=True,
            )
            result = _solve_one_sample(
                eq=eq,
                solver=solver,
                tokamak=tokamak,
                profiles_kwargs=profiles_kwargs,
                solv=solv,
                mt_spec=mt_spec,
                bnd=bnd,
                grid=ea["grid"],
                t_i=float(t_i),
                ip_i=float(ip_i),
                pf_i=pf_i,
                mode=mode,
                l2_reg=l2_reg,
                tokamak_pickle=HERE / ".multitime_work" / "tokamak.pkl",
            )
            attempted.append({
                "solve_mode": mode,
                "status": result.get("status"),
                "iterations": result.get("iterations"),
                "rel_change": result.get("rel_change"),
                "duration_s": result.get("duration_s"),
                "error": result.get("error"),
            })
            if result.get("ok"):
                break
            print(
                f"[WARN] {mode} failed at t={t_i:.6f}s: "
                f"status={result.get('status')} error={result.get('error')}",
                flush=True,
            )

        entry = {
            "t": float(t_i),
            "ip": float(ip_i),
            "attempts": attempted,
            "status": "skipped",
            "solve_mode": None,
            "iterations": None,
            "rel_change": None,
            "duration_s": None,
            "error": None,
        }

        if result is not None and result.get("ok"):
            fl_rows.append([float(t_i)] + [float(v) for v in probes.calculate_fluxloop_value(eq)])
            pu_rows.append([float(t_i)] + [float(v) for v in probes.calculate_pickup_value(eq)])
            mode_used = str(result.get("solve_mode"))
            entry.update({
                "status": str(result.get("status") or "converged"),
                "solve_mode": mode_used,
                "iterations": result.get("iterations"),
                "rel_change": result.get("rel_change"),
                "duration_s": result.get("duration_s"),
                "error": result.get("error"),
            })
            if mode_used == "full_inverse" and entry["status"] == "converged":
                n_inverse += 1
            elif mode_used == "forward_gs":
                n_forward += 1
            print(
                f"[OK] window sample {mode_used}: t={t_i:.6f}s "
                f"status={entry['status']} iters={result.get('iterations')} "
                f"rel_change={result.get('rel_change')} "
                f"duration_s={result.get('duration_s')}",
                flush=True,
            )
            # Presentation frame (formed-plasma window sample)
            try:
                from mast_freegsnke.equilibrium_presentation import (
                    save_equilibrium_png,
                    try_load_presentation_authority,
                )
                _pres = try_load_presentation_authority(INPUTS)
                if _pres is not None and _pres.write_eq_frames:
                    _frames_dir = HERE / "presentation" / "inverse_frames"
                    _tag = f"eq_t{t_i:.6f}".replace(".", "p")
                    _png = save_equilibrium_png(
                        tokamak=tokamak,
                        eq=eq,
                        out_path=_frames_dir / f"{_tag}.png",
                        title=f"Inverse {mode_used}  t={t_i:.4f}s  Ip={ip_i/1e6:.3f}MA",
                        dpi=int(_pres.gif_dpi),
                    )
                    entry["frame_png"] = str(_png.relative_to(HERE)).replace("\\", "/")
            except Exception as _pe:
                print(f"[WARN] inverse frame failed at t={t_i:.6f}s: {_pe}", flush=True)
        else:
            err = None if result is None else result.get("error")
            entry.update({
                "status": "skipped",
                "error": err or "all solve attempts failed",
            })
            n_skipped += 1
            print(f"[SKIP] t={t_i:.6f}s: {entry['error']}", flush=True)
        per_time.append(entry)

    if not fl_rows:
        raise RuntimeError(
            "Multi-time synthetic diagnostics produced zero solved times; "
            "cannot emit synthetic probe CSVs (never fabricate values)."
        )

    if n_inverse == len(fl_rows) and n_forward == 0:
        overall_mode = "full_inverse"
    elif n_forward == len(fl_rows) and n_inverse == 0:
        overall_mode = "forward_gs_at_measured_pf_ip"
    else:
        overall_mode = "mixed_inverse_and_forward_gs"

    out_dir = HERE / "synthetic"
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(fl_rows, columns=["time"] + fl_names).to_csv(out_dir / "synthetic_fluxloops.csv", index=False)
    pd.DataFrame(pu_rows, columns=["time"] + pu_names).to_csv(out_dir / "synthetic_pickups.csv", index=False)
    (out_dir / "synthetic_times.json").write_text(json.dumps(
        {
            **tb_meta,
            "times": [row["t"] for row in per_time if row.get("solve_mode")],
            "t0_formed_plasma": float(t0),
            "solve_mode": overall_mode,
            "n_inverse_converged": n_inverse,
            "n_forward_gs_fallback": n_forward,
            "n_skipped": n_skipped,
            "multitime_authority": mt_spec,
            "per_time": per_time,
            "note": (
                "Preferred path is full FreeGSNKE inverse at each window sample "
                "with a fresh Inverse_optimizer, sample-to-sample continuation, "
                "declared max_solving_iterations and per_time_timeout_s. Reusing "
                "one Inverse_optimizer across times stalls in FreeGSNKE 3.0.1 "
                "(uncapped while new_residual_flag resize loop inside "
                "GSstaticsolver.forward_solve calling freegs4e.critical.fastcrit). "
                "Hard per-sample kill is multiprocessing terminate on per_time_timeout_s; FreeGSNKERunner also enforces freegsnke_script_timeout_s. "
                "Failed times fall back to forward_gs or are skipped; never fabricated."
            ),
        },
        indent=2,
    ) + "\n")
    print(
        f"Saved synthetic/synthetic_fluxloops.csv ({len(fl_names)} loops) and "
        f"synthetic/synthetic_pickups.csv ({len(pu_names)} pickups) at "
        f"{len(fl_rows)} window sample times "
        f"(inverse={n_inverse}, forward_gs={n_forward}, skipped={n_skipped})"
    )

    # Stitch inverse equilibrium GIF across successful window samples
    try:
        from mast_freegsnke.equilibrium_presentation import (
            sorted_frame_paths,
            try_load_presentation_authority,
            write_gif_from_pngs,
        )
        _pres = try_load_presentation_authority(INPUTS)
        if _pres is not None and _pres.write_equilibrium_gifs:
            _frames = sorted_frame_paths(HERE / "presentation" / "inverse_frames", "eq_t*.png")
            _gif_rep = write_gif_from_pngs(
                _frames,
                HERE / "presentation" / "inverse_equilibria.gif",
                fps=float(_pres.gif_fps),
            )
            (HERE / "presentation" / "inverse_gif_report.json").write_text(
                json.dumps(_gif_rep, indent=2) + "\n", encoding="utf-8"
            )
            if _gif_rep.get("ok"):
                print(f"[OK] Wrote presentation/inverse_equilibria.gif ({_gif_rep.get('n_frames')} frames)")
            else:
                print(f"[WARN] inverse GIF not written: {_gif_rep.get('errors')}")
    except Exception as _ge:
        print(f"[WARN] inverse GIF stage failed: {_ge}", flush=True)


def set_machine_currents(tokamak, currents_dict):
    for name, coil in getattr(tokamak, "coils", []):
        if name in currents_dict and hasattr(coil, "current"):
            coil.current = float(currents_dict[name])

def get_control_coil_names(tokamak):
    names = []
    for name, coil in getattr(tokamak, "coils", []):
        if hasattr(coil, "control") and coil.control:
            names.append(name)
    return names

def main():
    ea = _load_execution_authority_bundle()
    grid = ea["grid"]
    prof = ea["profile"]
    bnd = ea["boundary"]
    solv = ea["solver"]

    ip_df = pd.read_csv(INPUTS / "ip.csv")
    t0, ip0, ip_max = choose_formed_plasma_time(ip_df, frac=__FORMED_FRAC__)
    print(f"Selected formed-plasma time t0={t0:.6f} s  Ip={ip0/1e6:.3f} MA")

    tokamak = build_machine.tokamak(
        active_coils_path=str(MACHINE / "active_coils.pickle"),
        passive_coils_path=str(MACHINE / "passive_coils.pickle"),
        limiter_path=str(MACHINE / "limiter.pickle"),
        wall_path=str(MACHINE / "wall.pickle"),
        magnetic_probe_path=(
            str(HERE / "magnetic_probes.pickle")
            if (HERE / "magnetic_probes.pickle").exists()
            else (
                str(MACHINE / "magnetic_probes.pickle")
                if (MACHINE / "magnetic_probes.pickle").exists()
                else None
            )
        ),
    )
    pf_init = load_pf_currents(t0)
    set_machine_currents(tokamak, pf_init)

    figm, axm = plt.subplots(1,1, figsize=(4,8), dpi=120)
    tokamak.plot(axis=axm, show=False)
    axm.plot(tokamak.limiter.R, tokamak.limiter.Z, "k--", lw=1.2, label="Limiter")
    axm.plot(tokamak.wall.R, tokamak.wall.Z, "k-", lw=1.2, label="Wall")
    axm.set_aspect("equal"); axm.grid(alpha=0.4)
    figm.tight_layout()
    figm.savefig(HERE/"machine.png", dpi=250, bbox_inches="tight")

    eq = equilibrium_update.Equilibrium(
        tokamak=tokamak,
        Rmin=float(grid["Rmin"]), Rmax=float(grid["Rmax"]),
        Zmin=float(grid["Zmin"]), Zmax=float(grid["Zmax"]),
        nx=int(grid["nx"]), ny=int(grid["ny"]),
    )

    profiles = ConstrainPaxisIp(
        eq=eq,
        paxis=float(prof["paxis_Pa"]),
        Ip=ip0,
        fvac=float(prof["fvac"]),
        alpha_m=float(prof["alpha_m"]),
        alpha_n=float(prof["alpha_n"]),
    )

    # Boundary / inverse constraints (execution-authority controlled)
    null_points = bnd["null_points"]
    isoflux_set = np.array(bnd["isoflux_set"], dtype=float)
    constrain = Inverse_optimizer(null_points=null_points, isoflux_set=isoflux_set)

    solver = GSstaticsolver.NKGSsolver(eq)

    # --- v10.0.0: internal solver state introspection & default-detection sentinel ---
    try:
        from mast_freegsnke.solver_introspection import write_solver_introspection
        _INTROSPECT_AVAILABLE = True
    except Exception as _e:
        print(f"[WARN] solver_introspection module not available: {_e}")
        _INTROSPECT_AVAILABLE = False
    control_names = get_control_coil_names(eq.tokamak)
    l2 = solv.get("l2_reg", {})
    l2_default = float(l2.get("default", 0.0))
    l2_over = dict(l2.get("per_coil_override", {}))
    l2_reg = np.array([l2_default]*len(control_names), dtype=float)
    for cname, val in l2_over.items():
        if cname in control_names:
            l2_reg[control_names.index(cname)] = float(val)

    solver.solve(
        eq=eq,
        profiles=profiles,
        constrain=constrain,
        target_relative_tolerance=float(solv["inverse_target_relative_tolerance"]),
        target_relative_psit_update=float(solv["inverse_target_relative_psit_update"]),
        verbose=True,
        l2_reg=l2_reg,
    )


    if _INTROSPECT_AVAILABLE:
        try:
            write_solver_introspection(
                HERE,
                execution_authority_bundle=ea,
                objects={
                    "tokamak": tokamak,
                    "eq": eq,
                    "profiles": profiles,
                    "constrain": constrain,
                    "solver": solver,
                },
            )
            print("[OK] Wrote solver_introspection/")
        except Exception as _e:
            print(f"[WARN] solver introspection failed: {_e}")
    import pickle
    pn = np.linspace(0.0, 1.0, 401)
    fvac_val = profiles.fvac() if callable(getattr(profiles, "fvac", None)) else float(profiles.fvac)
    coil_currents = {cname: float(coil.current) for cname, coil in getattr(eq.tokamak, "coils", []) if hasattr(coil, "current")}
    dump = dict(
        execution_authority_bundle=ea,
        pn=pn,
        pprime=np.array([profiles.pprime(x) for x in pn], dtype=float),
        ffprime=np.array([profiles.ffprime(x) for x in pn], dtype=float),
        fvac=float(fvac_val),
        profile_kwargs=dict(paxis=float(profiles.paxis), Ip=float(profiles.Ip), alpha_m=float(profiles.alpha_m), alpha_n=float(profiles.alpha_n)),
        plasma_psi=np.array(eq.plasma_psi, dtype=float),
        grid=dict(R=np.array(eq.R, dtype=float), Z=np.array(eq.Z, dtype=float), nx=int(eq.nx), ny=int(eq.ny)),
        coil_currents=coil_currents,
        t0=float(t0),
        Ip=float(ip0),
    )
    with open(HERE/"inverse_dump.pkl", "wb") as f:
        pickle.dump(dump, f)
    print("Saved inverse_dump.pkl")

    fig, ax = plt.subplots(1,1, figsize=(6,10), dpi=140)
    tokamak.plot(axis=ax, show=False)
    eq.plot(axis=ax, show=False)
    # Plot primary null-point targets if available
    try:
        Rx, Ro = float(null_points[0][0]), float(null_points[0][1])
        Zx, Zo = float(null_points[1][0]), float(null_points[1][1])
        ax.plot(Rx, Zx, "rx", ms=10, label="X target")
        ax.plot(Ro, Zo, "bo", ms=6, label="O target")
    except Exception:
        pass
    ax.set_aspect("equal"); ax.grid(alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(HERE/"inverse_equilibrium.png", dpi=250, bbox_inches="tight")
    print("Saved inverse_equilibrium.png")

    # Multi-time synthetic probe diagnostics (contract metrics input, v10.5.0).
    # Runs LAST in child processes so the t0 inverse dump/plots stay pristine.
    write_synthetic_probe_csvs(
        tokamak=tokamak,
        eq=eq,
        profiles_kwargs=dict(
            paxis=float(prof["paxis_Pa"]),
            fvac=float(prof["fvac"]),
            alpha_m=float(prof["alpha_m"]),
            alpha_n=float(prof["alpha_n"]),
        ),
        solver=solver,
        solv=solv,
        ea=ea,
        ip_df=ip_df,
        t0=t0,
    )

if __name__ == "__main__":
    main()
