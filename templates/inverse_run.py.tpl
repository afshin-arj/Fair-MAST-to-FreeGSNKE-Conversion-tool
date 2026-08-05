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
import os
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


def _make_inverse_constrain(bnd: dict):
    """Build Inverse_optimizer from boundary dict (optional coil_current_limits)."""
    kwargs = dict(
        null_points=bnd["null_points"],
        isoflux_set=np.array(bnd["isoflux_set"], dtype=float),
    )
    lim = bnd.get("coil_current_limits")
    if lim is not None:
        kwargs["coil_current_limits"] = np.array(lim, dtype=float)
    return Inverse_optimizer(**kwargs)


def _boundary_for_time(ea_bnd: dict, t_i: float) -> dict:
    """Per-sample Inverse boundary from nearest shape_targets knot (no invent)."""
    try:
        from mast_freegsnke.boundary_from_shape import boundary_dict_at_time

        return boundary_dict_at_time(INPUTS, t_s=float(t_i), fallback=ea_bnd)
    except Exception as e:
        print(f"[WARN] boundary_at_t={t_i:.6f} fallback to execution_authority: {e}", flush=True)
        return ea_bnd


def _null_topology_hint():
    try:
        prov = INPUTS / "execution_authority" / "boundary_from_shape_targets.json"
        if prov.is_file():
            return json.loads(prov.read_text(encoding="utf-8")).get("null_topology")
    except Exception:
        return None
    return None


def _with_retry_knobs(solv: dict, mt_spec: dict, l2_reg):
    """Declared FreeGSNKE knob overrides for shape-retry (no forged stop)."""
    retry = solv.get("inverse_shape_retry") if isinstance(solv.get("inverse_shape_retry"), dict) else {}
    solv2 = dict(solv)
    mt2 = dict(mt_spec)
    if retry.get("inverse_target_relative_tolerance") is not None:
        solv2["inverse_target_relative_tolerance"] = float(
            retry["inverse_target_relative_tolerance"]
        )
    if retry.get("inverse_target_relative_psit_update") is not None:
        solv2["inverse_target_relative_psit_update"] = float(
            retry["inverse_target_relative_psit_update"]
        )
    if retry.get("max_solving_iterations") is not None:
        mt2["max_solving_iterations"] = int(retry["max_solving_iterations"])
    l2_2 = np.asarray(l2_reg, dtype=float).copy()
    if retry.get("l2_reg_default") is not None and l2_2.size:
        # Scale all entries toward declared tighter default (keep relative per-coil ratios).
        base = float((solv.get("l2_reg") or {}).get("default", l2_2[0]) or l2_2[0])
        new_def = float(retry["l2_reg_default"])
        if base > 0.0:
            l2_2 = l2_2 * (new_def / base)
        else:
            l2_2[:] = new_def
    return solv2, mt2, l2_2


def _score_shape_now(eq, profiles, bnd: dict, ip: float, loss, solv: dict) -> dict:
    from mast_freegsnke.equilibrium_presentation import attach_profiles_after_restore
    from mast_freegsnke.inverse_shape_honesty import score_inverse_shape

    try:
        attach_profiles_after_restore(eq, profiles)
    except Exception:
        pass
    acc = solv.get("inverse_shape_acceptance")
    if not isinstance(acc, dict):
        acc = None
    return score_inverse_shape(
        eq=eq,
        null_points=bnd.get("null_points"),
        ip=float(ip),
        constrain_loss_final=loss,
        null_topology=_null_topology_hint(),
        acceptance=acc,
    )


def _apply_shape_gate_and_retry(
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
    l2_reg,
    result: dict,
    tokamak_pickle,
    restore_optimized_currents: bool = True,
):
    """After GS-ok Inverse: score shape; optional declared FreeGSNKE re-solve.

    Returns (result, shape_audit, attempts).
    """
    from mast_freegsnke.inverse_shape_honesty import apply_acceptance_status
    from freegsnke.jtor_update import ConstrainPaxisIp as _CPA

    attempts = []
    profiles = _CPA(eq=eq, Ip=float(ip_i), **profiles_kwargs)
    audit = _score_shape_now(
        eq, profiles, bnd, float(ip_i), result.get("constrain_loss_final"), solv
    )
    gate = apply_acceptance_status(
        gs_ok=bool(result.get("ok")),
        gs_status=str(result.get("status") or ""),
        audit=audit,
    )
    attempts.append(
        {
            "attempt": 0,
            "rel_change": result.get("rel_change"),
            "constrain_loss_final": result.get("constrain_loss_final"),
            "shape_status": audit.get("shape_status"),
            "shape_accepted": gate.get("shape_accepted"),
            "fail_reasons": list(audit.get("fail_reasons") or []),
        }
    )
    print(
        f"[INFO] inverse shape_audit t={float(t_i):.6f}: status={audit.get('shape_status')} "
        f"accepted={gate.get('shape_accepted')} "
        f"n_xpt={(audit.get('critical') or {}).get('n_xpt')} "
        f"reasons={audit.get('fail_reasons')}",
        flush=True,
    )

    retry = solv.get("inverse_shape_retry") if isinstance(solv.get("inverse_shape_retry"), dict) else {}
    max_retries = int(retry.get("max_retries", 0) or 0)
    attempt = 0
    while (
        bool(result.get("ok"))
        and (not gate.get("shape_accepted"))
        and attempt < max_retries
    ):
        attempt += 1
        solv2, mt2, l2_2 = _with_retry_knobs(solv, mt_spec, l2_reg)
        print(
            f"[..] shape retry {attempt}/{max_retries} at t={float(t_i):.6f} "
            f"tol={solv2.get('inverse_target_relative_tolerance')} "
            f"max_iter={mt2.get('max_solving_iterations')} "
            f"l2_default={float(np.asarray(l2_2).ravel()[0]) if np.size(l2_2) else None}",
            flush=True,
        )
        retry_res = _solve_one_sample(
            eq=eq,
            solver=solver,
            tokamak=tokamak,
            profiles_kwargs=profiles_kwargs,
            solv=solv2,
            mt_spec=mt2,
            bnd=bnd,
            grid=grid,
            t_i=float(t_i),
            ip_i=float(ip_i),
            pf_i=pf_i,
            mode="full_inverse",
            l2_reg=l2_2,
            tokamak_pickle=tokamak_pickle,
            restore_optimized_currents=restore_optimized_currents,
        )
        if not retry_res.get("ok"):
            attempts.append(
                {
                    "attempt": attempt,
                    "rel_change": retry_res.get("rel_change"),
                    "constrain_loss_final": retry_res.get("constrain_loss_final"),
                    "shape_status": "retry_gs_failed",
                    "shape_accepted": False,
                    "error": retry_res.get("error"),
                }
            )
            print(
                f"[WARN] shape retry {attempt} GS failed: {retry_res.get('error')}",
                flush=True,
            )
            break
        result = dict(retry_res)
        profiles = _CPA(eq=eq, Ip=float(ip_i), **profiles_kwargs)
        audit = _score_shape_now(
            eq, profiles, bnd, float(ip_i), result.get("constrain_loss_final"), solv
        )
        gate = apply_acceptance_status(
            gs_ok=True,
            gs_status=str(result.get("status") or "converged"),
            audit=audit,
        )
        attempts.append(
            {
                "attempt": attempt,
                "rel_change": result.get("rel_change"),
                "constrain_loss_final": result.get("constrain_loss_final"),
                "shape_status": audit.get("shape_status"),
                "shape_accepted": gate.get("shape_accepted"),
                "fail_reasons": list(audit.get("fail_reasons") or []),
            }
        )
        print(
            f"[INFO] shape retry {attempt} audit: status={audit.get('shape_status')} "
            f"accepted={gate.get('shape_accepted')}",
            flush=True,
        )

    result = dict(result)
    result["status"] = str(gate.get("status") or result.get("status"))
    result["ok"] = bool(gate.get("ok", result.get("ok")))
    result["shape_accepted"] = bool(gate.get("shape_accepted"))
    result["shape_audit"] = audit
    result["shape_attempts"] = attempts
    if gate.get("soft_skip"):
        result["soft_skip"] = True
    return result, audit, attempts


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
            constrain = _make_inverse_constrain(bnd)
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
            loss_hist = list(getattr(solver, "constrain_loss", []) or [])
            loss_final = None
            try:
                if loss_hist:
                    loss_final = float(loss_hist[-1])
            except Exception:
                loss_final = None
            tol = float(solv["inverse_target_relative_tolerance"])
            duration_s = float(_time.time() - tic)
            if duration_s > float(mt_spec["per_time_timeout_s"]):
                return {
                    "ok": False,
                    "status": "timeout",
                    "solve_mode": mode,
                    "iterations": iters,
                    "rel_change": rel,
                    "constrain_loss_final": loss_final,
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
                    "constrain_loss_final": loss_final,
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
                "constrain_loss_final": loss_final,
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
        coils_out = payload.get("coil_currents_json")
        if coils_out:
            coil_currents = {
                str(cname): float(coil.current)
                for cname, coil in getattr(eq.tokamak, "coils", [])
                if hasattr(coil, "current")
            }
            Path(coils_out).write_text(json.dumps(coil_currents) + "\n", encoding="utf-8")
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
    restore_optimized_currents: bool = False,
):
    """Solve one window sample with a hard wall-clock kill (multiprocessing).

    FreeGSNKE 3.0.1 can hang forever inside an uncapped residual-resize loop;
    soft post-hoc timing cannot escape that. A spawn child is terminated when
    ``per_time_timeout_s`` elapses so fallback_mode can still run.

    When ``restore_optimized_currents`` is True (t0 inverse IC), parent tokamak
    currents are restored from the child solution so ``inverse_dump.pkl`` keeps
    optimised PF currents. Multi-time synthetic keeps measured PF (default).
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
    coils_json = work / f"{tag}_coils.json"
    for pth in (psi_out, result_json, coils_json):
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
        "coil_currents_json": str(coils_json),
    }

    ctx = _mp.get_context("spawn")
    proc = ctx.Process(target=_multitime_solve_worker, args=(payload,))
    tic = _time.time()
    proc.start()
    child_pid = int(proc.pid) if proc.pid else None
    # Windows: Process.join(timeout=…) can hang forever while the child is in
    # native FreeGSNKE/freegs4e code. Use a Timer + taskkill instead.
    import threading as _threading

    timed_out = {"v": False}

    def _force_kill_child() -> None:
        timed_out["v"] = True
        if child_pid:
            try:
                import subprocess as _sp

                if os.name == "nt":
                    _sp.run(
                        ["taskkill", "/F", "/T", "/PID", str(child_pid)],
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                else:
                    try:
                        os.kill(child_pid, 9)
                    except Exception:
                        pass
            except Exception:
                pass
        try:
            if proc.is_alive():
                proc.terminate()
            if proc.is_alive():
                proc.kill()
        except Exception:
            pass

    wd = _threading.Timer(float(mt_spec["per_time_timeout_s"]), _force_kill_child)
    wd.daemon = True
    wd.start()
    try:
        proc.join()
    finally:
        try:
            wd.cancel()
        except Exception:
            pass
    if timed_out["v"] or proc.is_alive():
        if proc.is_alive():
            _force_kill_child()
            try:
                proc.join(timeout=5.0)
            except Exception:
                pass
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
        if restore_optimized_currents and coils_json.exists():
            set_machine_currents(tokamak, json.loads(coils_json.read_text(encoding="utf-8")))
        else:
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
    _lcfs_series_rows = []
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

        bnd_i = _boundary_for_time(bnd, float(t_i))
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
                bnd=bnd_i,
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

        if result is not None and result.get("ok") and str(result.get("solve_mode")) == "full_inverse":
            try:
                _pf_now = {
                    str(cname): float(coil.current)
                    for cname, coil in getattr(tokamak, "coils", [])
                    if hasattr(coil, "current")
                }
                result, _aud_i, _att_i = _apply_shape_gate_and_retry(
                    eq=eq,
                    solver=solver,
                    tokamak=tokamak,
                    profiles_kwargs=profiles_kwargs,
                    solv=solv,
                    mt_spec=mt_spec,
                    bnd=bnd_i,
                    grid=ea["grid"],
                    t_i=float(t_i),
                    ip_i=float(ip_i),
                    pf_i=_pf_now,
                    l2_reg=l2_reg,
                    result=result,
                    tokamak_pickle=tokamak_pickle,
                    restore_optimized_currents=False,
                )
                entry["shape_audit"] = _aud_i
                entry["shape_attempts"] = _att_i
                entry["shape_accepted"] = result.get("shape_accepted")
            except Exception as _sg_e:
                print(f"[WARN] shape gate at t={t_i:.6f}s failed: {_sg_e}", flush=True)

        if result is not None and result.get("ok") and not result.get("soft_skip"):
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
            if mode_used == "full_inverse" and str(entry["status"]) in {
                "converged",
                "shape_accepted",
                "gs_converged_shape_unverified",
                "shape_plausible",
                "dn_missing_xpoints",
            }:
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
            # Capture LCFS polyline for EFIT side-by-side timeseries
            try:
                from mast_freegsnke.freegsnke_lcfs import lcfs_arrays_from_eq

                _lc = lcfs_arrays_from_eq(eq)
                if _lc is not None:
                    _lcfs_series_rows.append(
                        {"t": float(t_i), "R": _lc[0], "Z": _lc[1]}
                    )
            except Exception as _lce:
                print(f"[WARN] LCFS capture at t={t_i:.6f}s failed: {_lce}", flush=True)
            # Presentation frame (formed-plasma window sample)
            try:
                from mast_freegsnke.equilibrium_presentation import (
                    attach_profiles_after_restore,
                    save_equilibrium_png,
                    try_load_presentation_authority,
                )
                _pres = try_load_presentation_authority(INPUTS)
                if _pres is not None and _pres.write_eq_frames:
                    # Child restore only copies plasma_psi; refresh _profiles so
                    # native/curated contours are not blank (30201 inverse frames).
                    _prof_i = ConstrainPaxisIp(eq=eq, Ip=float(ip_i), **profiles_kwargs)
                    attach_profiles_after_restore(eq, _prof_i)
                    _frames_dir = HERE / "presentation" / "inverse_frames"
                    _tag = f"eq_t{t_i:.6f}".replace(".", "p")
                    _style = str(getattr(_pres, "plot_style", "curated") or "curated")
                    _constrain_i = None
                    if mode_used == "full_inverse":
                        try:
                            _constrain_i = _make_inverse_constrain(bnd_i)
                        except Exception:
                            _constrain_i = None
                    _dump_lcfs = None
                    try:
                        from mast_freegsnke.freegsnke_lcfs import lcfs_arrays_from_eq

                        _dump_lcfs = lcfs_arrays_from_eq(eq)
                    except Exception:
                        _dump_lcfs = None
                    _png = save_equilibrium_png(
                        tokamak=tokamak,
                        eq=eq,
                        out_path=_frames_dir / f"{_tag}.png",
                        title=(
                            f"Inverse {mode_used}  t={t_i:.4f}s  Ip={ip_i/1e6:.3f}MA"
                        ),
                        dpi=int(_pres.gif_dpi),
                        run_dir=HERE,
                        plot_style=_style,
                        profiles=_prof_i,
                        constrain=_constrain_i,
                        dump_lcfs=_dump_lcfs,
                    )
                    entry["frame_png"] = str(_png.relative_to(HERE)).replace("\\", "/")
            except Exception as _pe:
                print(f"[WARN] inverse frame failed at t={t_i:.6f}s: {_pe}", flush=True)
        else:
            err = None if result is None else result.get("error")
            if result is not None and result.get("soft_skip"):
                entry.update({
                    "status": str(result.get("status") or "gs_converged_shape_unverified"),
                    "solve_mode": str(result.get("solve_mode") or "full_inverse"),
                    "iterations": result.get("iterations"),
                    "rel_change": result.get("rel_change"),
                    "duration_s": result.get("duration_s"),
                    "error": "soft_skip_time: shape acceptance failed",
                    "shape_accepted": False,
                })
                n_skipped += 1
                print(
                    f"[SKIP] t={t_i:.6f}s soft_skip_time (shape gate): "
                    f"status={entry['status']} reasons="
                    f"{(entry.get('shape_audit') or {}).get('fail_reasons')}",
                    flush=True,
                )
            else:
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
    try:
        from mast_freegsnke.freegsnke_lcfs import write_freegsnke_lcfs_timeseries_csv

        for _ts_path in (
            HERE / "presentation" / "freegsnke_lcfs_timeseries.csv",
            HERE / "03_reconstruction" / "presentation" / "freegsnke_lcfs_timeseries.csv",
        ):
            _w = write_freegsnke_lcfs_timeseries_csv(_ts_path, _lcfs_series_rows)
            if _w is not None:
                print(f"[OK] Wrote FreeGSNKE LCFS timeseries ({len(_lcfs_series_rows)} knots): {_w}")
                break
    except Exception as _ts_e:
        print(f"[WARN] FreeGSNKE LCFS timeseries write failed: {_ts_e}")

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
    from mast_freegsnke.tokamak_currents import set_tokamak_currents

    set_tokamak_currents(tokamak, currents_dict)

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

    # Boundary / inverse constraints (execution-authority + per-t0 shape_targets)
    null_points = bnd["null_points"]
    isoflux_set = np.array(bnd["isoflux_set"], dtype=float)
    bnd_t0 = _boundary_for_time(bnd, float(t0))
    constrain = _make_inverse_constrain(bnd_t0)

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

    # t0 solve must use the same hard per-time kill + max_solving_iterations as
    # multitime. Uncapped in-process solver.solve can hang forever inside
    # freegs4e residual-resize / jtor (shot 30202: 1200s script timeout).
    mt_spec = _load_multitime_spec(solv)
    profiles_kwargs = dict(
        paxis=float(prof["paxis_Pa"]),
        fvac=float(prof["fvac"]),
        alpha_m=float(prof["alpha_m"]),
        alpha_n=float(prof["alpha_n"]),
    )
    modes_to_try = [mt_spec["preferred_mode"]]
    if mt_spec["fallback_mode"] == "forward_gs" and mt_spec["preferred_mode"] != "forward_gs":
        modes_to_try.append("forward_gs")
    t0_result = None
    t0_mode_used = None
    for mode in modes_to_try:
        print(
            f"[..] t0 {mode}: timeout={mt_spec['per_time_timeout_s']}s "
            f"max_iter={mt_spec['max_solving_iterations']}",
            flush=True,
        )
        t0_result = _solve_one_sample(
            eq=eq,
            solver=solver,
            tokamak=tokamak,
            profiles_kwargs=profiles_kwargs,
            solv=solv,
            mt_spec=mt_spec,
            bnd=bnd_t0,
            grid=ea["grid"],
            t_i=float(t0),
            ip_i=float(ip0),
            pf_i=pf_init,
            mode=mode,
            l2_reg=l2_reg,
            tokamak_pickle=HERE / ".multitime_work" / "tokamak.pkl",
            restore_optimized_currents=(mode == "full_inverse"),
        )
        if t0_result.get("ok"):
            t0_mode_used = mode
            print(
                f"[OK] t0 {mode}: status={t0_result.get('status')} "
                f"iters={t0_result.get('iterations')} "
                f"rel_change={t0_result.get('rel_change')} "
                f"duration_s={t0_result.get('duration_s')}",
                flush=True,
            )
            break
        print(
            f"[WARN] t0 {mode} failed: status={t0_result.get('status')} "
            f"error={t0_result.get('error')}",
            flush=True,
        )
    # Cold Inverse at formed-plasma t0 can stall (30201: rel_change~0.3) while the
    # same DN constraints converge on nearby window samples via continuation. If
    # forward_gs produced a physical psi at measured PF, retry Inverse once from
    # that seed (declared numeric strategy — not invented metrology).
    if (
        t0_result is not None
        and t0_result.get("ok")
        and t0_mode_used == "forward_gs"
        and mt_spec["preferred_mode"] == "full_inverse"
    ):
        print(
            "[..] t0 full_inverse retry after forward_gs seed "
            f"(timeout={mt_spec['per_time_timeout_s']}s, "
            f"max_iter={mt_spec['max_solving_iterations']})",
            flush=True,
        )
        retry = _solve_one_sample(
            eq=eq,
            solver=solver,
            tokamak=tokamak,
            profiles_kwargs=profiles_kwargs,
            solv=solv,
            mt_spec=mt_spec,
            bnd=bnd_t0,
            grid=ea["grid"],
            t_i=float(t0),
            ip_i=float(ip0),
            pf_i=pf_init,
            mode="full_inverse",
            l2_reg=l2_reg,
            tokamak_pickle=HERE / ".multitime_work" / "tokamak.pkl",
            restore_optimized_currents=True,
        )
        if retry.get("ok"):
            t0_result = retry
            t0_mode_used = "full_inverse"
            print(
                f"[OK] t0 full_inverse after forward_gs seed: "
                f"status={retry.get('status')} iters={retry.get('iterations')} "
                f"rel_change={retry.get('rel_change')} "
                f"duration_s={retry.get('duration_s')}",
                flush=True,
            )
        else:
            print(
                f"[WARN] t0 full_inverse retry failed; keeping forward_gs dump: "
                f"status={retry.get('status')} error={retry.get('error')}",
                flush=True,
            )
    if t0_result is None or not t0_result.get("ok"):
        err = None if t0_result is None else t0_result.get("error")
        print(
            f"[FAIL] t0 inverse failed after declared modes {modes_to_try}: {err}",
            flush=True,
        )
        raise SystemExit(2)
    # Refresh profiles / solver against the solved eq (child restored psi ± currents).
    profiles = ConstrainPaxisIp(eq=eq, Ip=float(ip0), **profiles_kwargs)
    solver = GSstaticsolver.NKGSsolver(eq)

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
    # Fresh ConstrainPaxisIp after hard-kill child restore has no L/Beta0 until Jtor.
    # Must run BEFORE LCFS extract + curated plot (30201: contours missing when
    # _profiles.xpt empty / LCFS extract ran pre-Jtor).
    try:
        from mast_freegsnke.equilibrium_presentation import attach_profiles_after_restore

        if not attach_profiles_after_restore(eq, profiles):
            raise RuntimeError("attach_profiles_after_restore returned False")
    except Exception as _jtor_e:
        print(f"[WARN] profile Jtor normalise failed: {_jtor_e}", flush=True)
        try:
            _psi_for_jtor = eq.psi() if callable(getattr(eq, "psi", None)) else getattr(eq, "psi", None)
            if _psi_for_jtor is None:
                raise RuntimeError("eq.psi unavailable for Jtor normalise")
            profiles.Jtor(eq.R, eq.Z, np.asarray(_psi_for_jtor, dtype=float))
            eq._profiles = profiles
        except Exception as _jtor_e2:
            print(f"[WARN] profile Jtor fallback failed: {_jtor_e2}", flush=True)
    # Honest shape audit + optional declared FreeGSNKE re-solve (GS stop unchanged).
    _shape_audit = None
    _shape_attempts = []
    if t0_result.get("ok") and str(t0_mode_used) == "full_inverse":
        try:
            _pf_now = {
                str(cname): float(coil.current)
                for cname, coil in getattr(tokamak, "coils", [])
                if hasattr(coil, "current")
            }
            t0_result, _shape_audit, _shape_attempts = _apply_shape_gate_and_retry(
                eq=eq,
                solver=solver,
                tokamak=tokamak,
                profiles_kwargs=profiles_kwargs,
                solv=solv,
                mt_spec=mt_spec,
                bnd=bnd_t0,
                grid=grid,
                t_i=float(t0),
                ip_i=float(ip0),
                pf_i=_pf_now,
                l2_reg=l2_reg,
                result=t0_result,
                tokamak_pickle=HERE / ".multitime_work" / "tokamak.pkl",
                restore_optimized_currents=True,
            )
            t0_mode_used = str(t0_result.get("solve_mode") or t0_mode_used)
            if not t0_result.get("ok") and not t0_result.get("soft_skip"):
                acc = solv.get("inverse_shape_acceptance") or {}
                if str(acc.get("on_fail") or "") == "blocking":
                    raise SystemExit(
                        f"Inverse t0 shape gate blocking: {t0_result.get('status')} "
                        f"reasons={(_shape_audit or {}).get('fail_reasons')}"
                    )
            # Refresh ConstrainPaxisIp after possible retry restore
            profiles = ConstrainPaxisIp(eq=eq, Ip=float(ip0), **profiles_kwargs)
            from mast_freegsnke.equilibrium_presentation import attach_profiles_after_restore

            attach_profiles_after_restore(eq, profiles)
            constrain = _make_inverse_constrain(bnd_t0)
            fvac_val = profiles.fvac() if callable(getattr(profiles, "fvac", None)) else float(profiles.fvac)
        except SystemExit:
            raise
        except Exception as _sa_e:
            print(f"[WARN] inverse shape_gate failed: {_sa_e}", flush=True)
    coil_currents = {
        cname: float(coil.current)
        for cname, coil in getattr(eq.tokamak, "coils", [])
        if hasattr(coil, "current")
    }
    # Persist LCFS polyline so EFIT side-by-side / scorecard can load without eq object
    _lcfs_R = _lcfs_Z = None
    try:
        from mast_freegsnke.freegsnke_lcfs import lcfs_arrays_from_eq, persist_lcfs_from_eq

        _lcfs = lcfs_arrays_from_eq(eq)
        if _lcfs is not None:
            _lcfs_R, _lcfs_Z = np.asarray(_lcfs[0], dtype=float), np.asarray(_lcfs[1], dtype=float)
            _pers = persist_lcfs_from_eq(HERE, eq, time_s=float(t0))
            if _pers.get("ok"):
                print(f"[OK] Wrote FreeGSNKE LCFS ({_pers.get('n_points')} pts): {_pers.get('paths')}")
            else:
                print(f"[WARN] FreeGSNKE LCFS persist failed: {_pers.get('error')}")
        else:
            print("[WARN] FreeGSNKE LCFS extract returned None after inverse")
    except Exception as _lcfs_e:
        print(f"[WARN] FreeGSNKE LCFS extract failed: {_lcfs_e}")
    _pprime = _ffprime = None
    try:
        _pprime = np.array([profiles.pprime(x) for x in pn], dtype=float)
        _ffprime = np.array([profiles.ffprime(x) for x in pn], dtype=float)
    except Exception as _pp_e:
        print(f"[WARN] pprime/ffprime dump skipped: {_pp_e}", flush=True)
    dump = dict(
        execution_authority_bundle=ea,
        pn=pn,
        pprime=_pprime,
        ffprime=_ffprime,
        fvac=float(fvac_val),
        profile_kwargs=dict(paxis=float(profiles.paxis), Ip=float(profiles.Ip), alpha_m=float(profiles.alpha_m), alpha_n=float(profiles.alpha_n)),
        plasma_psi=np.array(eq.plasma_psi, dtype=float),
        grid=dict(R=np.array(eq.R, dtype=float), Z=np.array(eq.Z, dtype=float), nx=int(eq.nx), ny=int(eq.ny)),
        coil_currents=coil_currents,
        t0=float(t0),
        Ip=float(ip0),
        lcfs_R=_lcfs_R,
        lcfs_Z=_lcfs_Z,
        t0_solve_mode=str(t0_mode_used),
        t0_solve_status=str(t0_result.get("status") or ""),
        t0_solve_duration_s=t0_result.get("duration_s"),
        t0_solve_iterations=t0_result.get("iterations"),
        t0_rel_change=t0_result.get("rel_change"),
        t0_constrain_loss_final=t0_result.get("constrain_loss_final"),
        shape_audit=_shape_audit,
        shape_attempts=_shape_attempts,
    )
    # Total ψ (plasma + coils) for honest EFIT side-by-side coloring (not plasma_psi alone)
    try:
        _psi_total = eq.psi() if callable(getattr(eq, "psi", None)) else getattr(eq, "psi", None)
        if _psi_total is not None:
            dump["total_psi"] = np.asarray(_psi_total, dtype=float)
    except Exception as _psi_e:
        print(f"[WARN] total_psi extract failed: {_psi_e}")
    try:
        from mast_freegsnke.shape_scorecard import extract_freegsnke_shape_targets

        _shp = extract_freegsnke_shape_targets(eq)
        for _k in (
            "magnetic_axis_r",
            "magnetic_axis_z",
            "x_point_r",
            "x_point_z",
            "R_in_m",
            "R_out_m",
        ):
            if _shp.get(_k) is not None:
                dump[_k] = _shp.get(_k)
    except Exception as _shp_e:
        print(f"[WARN] shape targets extract failed: {_shp_e}")
    with open(HERE/"inverse_dump.pkl", "wb") as f:
        pickle.dump(dump, f)
    print("Saved inverse_dump.pkl")
    # JSON-safe shape gate provenance (science_audit / SUMMARY; no forged GS stop)
    try:
        _shape_json = {
            "status": str(t0_result.get("status") or ""),
            "shape_accepted": bool(t0_result.get("shape_accepted"))
            if t0_result.get("shape_accepted") is not None
            else None,
            "rel_change": t0_result.get("rel_change"),
            "constrain_loss_final": t0_result.get("constrain_loss_final"),
            "iterations": t0_result.get("iterations"),
            "duration_s": t0_result.get("duration_s"),
            "solve_mode": str(t0_mode_used),
            "shape_audit": _shape_audit,
            "shape_attempts": _shape_attempts,
            "notes": [
                "FreeGSNKE Inverse stop = GS residual / relative ψ update only.",
                "shape_audit uses declared solver.inverse_shape_acceptance thresholds.",
            ],
        }
        (HERE / "inverse_result.json").write_text(
            json.dumps(_shape_json, indent=2, default=str) + "\n", encoding="utf-8"
        )
        print("Saved inverse_result.json (shape gate provenance)")
    except Exception as _sj_e:
        print(f"[WARN] inverse_result.json failed: {_sj_e}", flush=True)

    # Plot is best-effort — never abort after a successful dump (shot 30202:
    # hard-kill restore leaves eq without _profiles; freegs4e.plot raises).
    try:
        from mast_freegsnke.equilibrium_presentation import (
            load_inverse_null_targets,
            save_equilibrium_png,
            try_load_presentation_authority,
        )

        _pres = try_load_presentation_authority(INPUTS)
        _style = str(
            getattr(_pres, "plot_style", "curated") if _pres else "curated"
        )
        _dump_lcfs = None
        if _lcfs_R is not None and _lcfs_Z is not None:
            _dump_lcfs = (_lcfs_R, _lcfs_Z)
        _title = f"Inverse {t0_mode_used} t0={float(t0):.4f}s Ip={float(ip0)/1e6:.3f}MA"
        if _shape_audit and str(_shape_audit.get("shape_status") or "") not in {
            "",
            "shape_plausible",
        }:
            _title += f" [{_shape_audit.get('shape_status')}]"
        save_equilibrium_png(
            tokamak=tokamak,
            eq=eq,
            out_path=HERE / "inverse_equilibrium.png",
            title=_title,
            dpi=250,
            figsize=(6.0, 10.0),
            run_dir=HERE,
            plot_style=_style,
            profiles=profiles,
            constrain=constrain,
            inverse_targets=load_inverse_null_targets(HERE),
            dump_lcfs=_dump_lcfs,
        )
        print(f"Saved inverse_equilibrium.png (plot_style={_style})")
    except Exception as _fig_e:
        print(f"[WARN] inverse_equilibrium.png failed: {_fig_e}", flush=True)

    # ADR-001 optional TORAX GEQDSK export (authority-gated; default off).
    # After inverse_dump.pkl, export failure must not abort the child (dump +
    # synthetics stay valid). Pipeline fail-closes on missing/empty GEQDSK when
    # export_torax_geometry=true — without cascade-skipping EFIT/planner peers.
    _tg = None
    try:
        from mast_freegsnke.torax_geometry_export import (
            export_torax_geqdsk_from_equilibrium,
            try_load_torax_geometry_export_authority,
        )
        _tg = try_load_torax_geometry_export_authority(INPUTS)
        if _tg is not None:
            _shot = int(HERE.name) if str(HERE.name).isdigit() else None
            _rep = export_torax_geqdsk_from_equilibrium(
                HERE, eq, _tg, shot=_shot, t0=float(t0)
            )
            print(
                f"[OK] TORAX geometry export: {_rep.get('path')} "
                f"sha256={str(_rep.get('sha256'))[:16]}… "
                f"rcentr={_rep.get('rcentr_m')} "
                f"(profiles={_rep.get('profile_provenance')})",
                flush=True,
            )
        else:
            print("[INFO] TORAX geometry export skipped (no authority snapshot)", flush=True)
    except Exception as _tge:
        print(f"[WARN] torax geometry export failed: {_tge}", flush=True)
        try:
            if _tg is not None:
                _stub = HERE / str(_tg.output_relpath)
                if _stub.is_file() and _stub.stat().st_size <= 0:
                    _stub.unlink()
        except Exception:
            pass
        print(
            "[WARN] continuing after TORAX export failure "
            "(pipeline fail-closes if export_torax_geometry=true)",
            flush=True,
        )
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
