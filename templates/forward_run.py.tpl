#!/usr/bin/env python3
# Generated FreeGSNKE static forward replay solve (+ multi-time window frames/GIF)
#
# Author: © 2026 Afshin Arjhangmehr

from pathlib import Path
import json
import multiprocessing as _mp
import os
import pickle
import time as _time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from freegsnke import build_machine
from freegsnke import equilibrium_update
from freegsnke.jtor_update import ConstrainPaxisIp
from freegsnke import GSstaticsolver

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
MACHINE = Path(__MACHINE_DIR_REPR__)
DUMP = HERE / "inverse_dump.pkl"
ACTIVE_CIRCUITS = ["P2_inner", "P2_outer", "P3", "P4", "P5", "P6", "Solenoid"]


def _load_execution_authority_bundle_fallback() -> dict:
    bp = HERE / "inputs" / "execution_authority" / "execution_authority_bundle.json"
    if not bp.exists():
        raise FileNotFoundError("Missing execution authority bundle (fallback): " + str(bp))
    obj = json.loads(bp.read_text())
    if not isinstance(obj, dict):
        raise ValueError("Execution authority bundle must be a JSON object")
    return obj


def set_active_currents(tokamak, currents_dict):
    from mast_freegsnke.tokamak_currents import set_tokamak_currents

    filtered = {
        cname: currents_dict[cname]
        for cname in ACTIVE_CIRCUITS
        if cname in currents_dict
    }
    set_tokamak_currents(tokamak, filtered)


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
    for c in ACTIVE_CIRCUITS:
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
    mt = ea.get("metrics_timebase")
    if not isinstance(mt, dict):
        raise KeyError("Execution authority bundle missing 'metrics_timebase'")
    rule = str(mt["rule"])
    n = int(mt["n_times"])
    if rule != "linspace_window_inclusive":
        raise ValueError(f"Unsupported metrics_timebase rule: {rule}")
    wp = INPUTS / "window.json"
    if not wp.exists():
        raise RuntimeError("inputs/window.json missing: multi-time forward requires finalized window")
    w = json.loads(wp.read_text(encoding="utf-8"))
    t0 = float(w["t_start"])
    t1 = float(w["t_end"])
    if not (t1 > t0):
        raise RuntimeError(f"invalid window: t_start={t0} t_end={t1}")
    if n == 1:
        times = np.array([0.5 * (t0 + t1)], dtype=float)
    else:
        times = np.linspace(t0, t1, n, dtype=float)
    meta = {
        "rule": rule,
        "n_times": n,
        "t_start": t0,
        "t_end": t1,
        "times": [float(x) for x in times],
    }
    return times, meta


def _load_multitime_spec(solv: dict) -> dict:
    mt = (solv or {}).get("multitime") or {}
    return {
        "preferred_mode": str(mt.get("preferred_mode", "full_inverse")),
        "max_solving_iterations": int(mt.get("max_solving_iterations", 50)),
        "per_time_timeout_s": float(mt.get("per_time_timeout_s", 180.0)),
        "continuation": bool(mt.get("continuation", True)),
        "fallback_mode": str(mt.get("fallback_mode", "forward_gs")),
    }


def _forward_profile_source(solv: dict) -> str:
    src = str((solv or {}).get("forward_profile_source", "inverse_dump_frozen") or "inverse_dump_frozen")
    if src not in {"inverse_dump_frozen", "profile_trajectory"}:
        raise ValueError(
            f"unsupported solver.forward_profile_source={src!r} "
            "(use inverse_dump_frozen|profile_trajectory)"
        )
    return src


def _resolve_forward_profile_kwargs(
    *,
    dump_profile_kwargs: dict,
    t_i: float,
    source_requested: str,
) -> tuple:
    """Return (profile_kwargs, source_used). Never invent knobs."""
    frozen = {
        "paxis": float(dump_profile_kwargs["paxis"]),
        "fvac": float(dump_profile_kwargs["fvac"]),
        "alpha_m": float(dump_profile_kwargs["alpha_m"]),
        "alpha_n": float(dump_profile_kwargs["alpha_n"]),
    }
    if source_requested == "inverse_dump_frozen":
        return frozen, "inverse_dump_frozen"

    # profile_trajectory path
    require = False
    try:
        from mast_freegsnke.profile_trajectory import (
            interpolate_profile_at,
            load_profile_trajectory_policy,
            try_load_built_trajectory,
        )

        pol_path = INPUTS / "profile_trajectory_authority" / "profile_trajectory_authority.json"
        if pol_path.exists():
            require = bool(load_profile_trajectory_policy(pol_path).require)
        traj = try_load_built_trajectory(INPUTS)
        if traj is not None:
            kn = interpolate_profile_at(traj, float(t_i))
            return (
                {
                    "paxis": float(kn["paxis"]),
                    "fvac": float(kn["fvac"]),
                    "alpha_m": float(kn["alpha_m"]),
                    "alpha_n": float(kn["alpha_n"]),
                },
                "profile_trajectory",
            )
    except Exception as e:
        if require:
            raise RuntimeError(
                "solver.forward_profile_source=profile_trajectory but trajectory "
                f"unavailable/invalid: {e}. Fix profile_trajectory authority or set "
                "forward_profile_source=inverse_dump_frozen."
            ) from e
        print(
            f"[WARN] profile_trajectory unavailable at t={float(t_i):.6f}: {e}; "
            "falling back to inverse_dump_frozen",
            flush=True,
        )
        return frozen, "inverse_dump_frozen_fallback"

    if require:
        raise RuntimeError(
            "solver.forward_profile_source=profile_trajectory but no ok trajectory "
            "under inputs/profile_trajectory_authority/. Build profile_trajectory "
            "or set forward_profile_source=inverse_dump_frozen."
        )
    print(
        f"[WARN] profile_trajectory missing/not-ok at t={float(t_i):.6f}; "
        "falling back to inverse_dump_frozen",
        flush=True,
    )
    return frozen, "inverse_dump_frozen_fallback"


def _live_forward_lcfs(eq):
    """Extract live Forward LCFS polyline; never return Inverse dump LCFS."""
    try:
        from mast_freegsnke.freegsnke_lcfs import lcfs_arrays_from_eq

        return lcfs_arrays_from_eq(eq)
    except Exception:
        return None


def _save_forward_png(
    *,
    tokamak,
    eq,
    profiles,
    out_path,
    title: str,
    dpi: int,
    figsize,
    plot_style: str,
):
    """Forward plot: live LCFS only; never Inverse dump LCFS or Inverse targets."""
    from mast_freegsnke.equilibrium_presentation import (
        attach_profiles_after_restore,
        save_equilibrium_png,
    )

    attach_profiles_after_restore(eq, profiles)
    live = _live_forward_lcfs(eq)
    return save_equilibrium_png(
        tokamak=tokamak,
        eq=eq,
        out_path=out_path,
        title=title,
        dpi=int(dpi),
        figsize=figsize,
        run_dir=HERE,
        plot_style=str(plot_style or "curated"),
        profiles=profiles,
        dump_lcfs=live,
        use_inverse_dump_lcfs=False,
        use_inverse_targets=False,
        lcfs_label="LCFS (Forward)",
    )


def _forward_sample_worker(payload: dict) -> None:
    """Spawn-child: one forward GS sample (hard per_time_timeout_s kill)."""
    import pickle as _pickle

    tokamak = _pickle.loads(Path(payload["tokamak_pickle"]).read_bytes())
    grid = payload["grid"]
    eq = equilibrium_update.Equilibrium(
        tokamak=tokamak,
        Rmin=float(grid["Rmin"]), Rmax=float(grid["Rmax"]),
        Zmin=float(grid["Zmin"]), Zmax=float(grid["Zmax"]),
        nx=int(grid["nx"]), ny=int(grid["ny"]),
    )
    eq.plasma_psi = np.array(np.load(payload["plasma_psi_in"]), dtype=float, copy=True)
    eq.solved = False
    set_active_currents(tokamak, payload["pf_i"])
    pk = payload["profile_kwargs"]
    profiles = ConstrainPaxisIp(
        eq=eq,
        paxis=float(pk["paxis"]),
        Ip=float(payload["ip_i"]),
        fvac=float(pk["fvac"]),
        alpha_m=float(pk["alpha_m"]),
        alpha_n=float(pk["alpha_n"]),
    )
    solver = GSstaticsolver.NKGSsolver(eq)
    solv = payload["solv"]
    mt_spec = payload["mt_spec"]
    tic = _time.time()
    result = {
        "ok": False,
        "status": "error",
        "solve_mode": "forward_gs",
        "iterations": 0,
        "rel_change": None,
        "duration_s": 0.0,
        "error": None,
    }
    try:
        solver.solve(
            eq=eq,
            profiles=profiles,
            constrain=None,
            target_relative_tolerance=float(solv["forward_target_relative_tolerance"]),
            max_solving_iterations=int(mt_spec["max_solving_iterations"]),
            verbose=False,
        )
        rel = float(getattr(solver, "relative_change", float("nan")))
        iters = int(max(0, len(getattr(solver, "norm_rel_change", [])) - 1))
        duration_s = float(_time.time() - tic)
        tol = float(solv["forward_target_relative_tolerance"])
        status = "converged" if (np.isfinite(rel) and rel <= tol) else "completed_max_iter"
        err = None
        if status != "converged":
            err = (
                f"forward_gs finished without meeting tolerance: "
                f"rel_change={rel:.3e} vs {tol:.3e} in {iters} iterations"
            )
        result.update(
            {
                "ok": True,
                "status": status,
                "iterations": iters,
                "rel_change": rel,
                "duration_s": duration_s,
                "error": err,
            }
        )
        np.save(payload["plasma_psi_out"], np.asarray(eq.plasma_psi, dtype=float))
    except Exception as e:
        result.update(
            {
                "ok": False,
                "status": "error",
                "duration_s": float(_time.time() - tic),
                "error": f"{type(e).__name__}: {e}",
            }
        )
    Path(payload["result_json"]).write_text(json.dumps(result) + "\n", encoding="utf-8")


def _solve_forward_sample(
    *,
    eq,
    tokamak,
    grid: dict,
    solv: dict,
    mt_spec: dict,
    profile_kwargs: dict,
    t_i: float,
    ip_i: float,
    pf_i: dict,
    tokamak_pickle: Path,
) -> dict:
    import pickle as _pickle

    work = HERE / ".multitime_work"
    work.mkdir(parents=True, exist_ok=True)
    if not tokamak_pickle.exists():
        tokamak_pickle.write_bytes(_pickle.dumps(tokamak, protocol=5))

    tag = f"fwd_{t_i:.6f}".replace(".", "p")
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
        "solv": solv,
        "mt_spec": mt_spec,
        "profile_kwargs": {
            "paxis": float(profile_kwargs["paxis"]),
            "fvac": float(profile_kwargs["fvac"]),
            "alpha_m": float(profile_kwargs["alpha_m"]),
            "alpha_n": float(profile_kwargs["alpha_n"]),
        },
        "t_i": float(t_i),
        "ip_i": float(ip_i),
        "pf_i": {k: float(v) for k, v in pf_i.items()},
        "plasma_psi_in": str(psi_in),
        "plasma_psi_out": str(psi_out),
        "result_json": str(result_json),
    }

    ctx = _mp.get_context("spawn")
    proc = ctx.Process(target=_forward_sample_worker, args=(payload,))
    tic = _time.time()
    proc.start()
    child_pid = int(proc.pid) if proc.pid else None
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
            "solve_mode": "forward_gs",
            "iterations": None,
            "rel_change": None,
            "duration_s": float(_time.time() - tic),
            "error": (
                f"hard kill: per-time forward exceeded solver.multitime.per_time_timeout_s="
                f"{mt_spec['per_time_timeout_s']}s (child process terminated)"
            ),
        }

    if not result_json.exists():
        return {
            "ok": False,
            "status": "error",
            "solve_mode": "forward_gs",
            "iterations": None,
            "rel_change": None,
            "duration_s": float(_time.time() - tic),
            "error": f"child exited without result (exitcode={proc.exitcode})",
        }
    result = json.loads(result_json.read_text(encoding="utf-8"))
    if result.get("ok") and psi_out.exists():
        eq.plasma_psi = np.load(psi_out)
        eq.solved = True
        set_active_currents(tokamak, pf_i)
    return result


def main():
    with open(DUMP, "rb") as f:
        dump = pickle.load(f)

    ea = dump.get("execution_authority_bundle")
    if ea is None:
        ea = _load_execution_authority_bundle_fallback()
    grid = ea["grid"]
    solv = ea["solver"]
    mt_spec = _load_multitime_spec(solv)

    tokamak = build_machine.tokamak(
        active_coils_path=str(MACHINE / "active_coils.pickle"),
        passive_coils_path=str(MACHINE / "passive_coils.pickle"),
        limiter_path=str(MACHINE / "limiter.pickle"),
        wall_path=str(MACHINE / "wall.pickle"),
    )
    set_active_currents(tokamak, dump.get("coil_currents", {}))

    eq = equilibrium_update.Equilibrium(
        tokamak=tokamak,
        Rmin=float(grid["Rmin"]), Rmax=float(grid["Rmax"]),
        Zmin=float(grid["Zmin"]), Zmax=float(grid["Zmax"]),
        nx=int(grid["nx"]), ny=int(grid["ny"]),
    )

    pk = dump["profile_kwargs"]
    profile_kwargs = {
        "paxis": float(pk["paxis"]),
        "fvac": float(dump["fvac"]),
        "alpha_m": float(pk["alpha_m"]),
        "alpha_n": float(pk["alpha_n"]),
    }
    profiles = ConstrainPaxisIp(
        eq=eq,
        paxis=float(pk["paxis"]),
        Ip=float(pk["Ip"]),
        fvac=float(dump["fvac"]),
        alpha_m=float(pk["alpha_m"]),
        alpha_n=float(pk["alpha_n"]),
    )

    solver = GSstaticsolver.NKGSsolver(eq)

    # --- v10.0.0: internal solver state introspection & default-detection sentinel ---
    try:
        from mast_freegsnke.solver_introspection import write_solver_introspection
        _INTROSPECT_AVAILABLE = True
    except Exception as _e:
        print(f"[WARN] solver_introspection module not available: {_e}")
        _INTROSPECT_AVAILABLE = False
    solver.solve(
        eq=eq,
        profiles=profiles,
        constrain=None,
        target_relative_tolerance=float(solv["forward_target_relative_tolerance"]),
        max_solving_iterations=int(mt_spec["max_solving_iterations"]),
        verbose=True,
    )

    # Dump currents by default (= Inverse IC); measured-PF multitime is labeled below.
    try:
        from mast_freegsnke.equilibrium_presentation import try_load_presentation_authority

        _pres0 = try_load_presentation_authority(INPUTS)
        _style = str(
            getattr(_pres0, "plot_style", "curated") if _pres0 else "curated"
        )
        t0 = dump.get("t0")
        Ip = dump.get("Ip")
        _title = (
            f"Forward GS (dump currents) t0={float(t0):.4f}s Ip={float(Ip)/1e6:.3f}MA"
            if t0 is not None and Ip is not None
            else "Forward GS (dump currents)"
        )
        _save_forward_png(
            tokamak=tokamak,
            eq=eq,
            profiles=profiles,
            out_path=HERE / "forward_equilibrium.png",
            title=_title,
            dpi=250,
            figsize=(6.0, 10.0),
            plot_style=_style,
        )
        print(f"Saved forward_equilibrium.png (plot_style={_style})")
    except Exception as _fig_e:
        print(f"[WARN] forward_equilibrium.png failed: {_fig_e}", flush=True)

    # Multi-time forward GS across formed-plasma window → frames + GIF
    # Hard per-sample kill (same FreeGSNKE hang mode as inverse multi-time).
    try:
        from mast_freegsnke.equilibrium_presentation import (
            sorted_frame_paths,
            try_load_presentation_authority,
            write_gif_from_pngs,
        )
        pres = try_load_presentation_authority(INPUTS)
        if pres is not None and (pres.write_eq_frames or pres.write_equilibrium_gifs):
            ip_path = INPUTS / "ip.csv"
            if not ip_path.exists():
                raise FileNotFoundError(f"Missing {ip_path} for multi-time forward")
            ip_df = pd.read_csv(ip_path)
            times, tb_meta = compute_sample_times(ea)
            frames_dir = HERE / "presentation" / "forward_frames"
            per_time = []
            tokamak_pickle = HERE / ".multitime_work" / "tokamak_fwd.pkl"
            n_ok = 0
            n_skip = 0
            _plot_style = str(getattr(pres, "plot_style", "curated") or "curated")
            _src_req = _forward_profile_source(solv)
            _src_used_rollup = set()
            # Continue from the t0 forward solution (cold-start each sample can hang).
            if not mt_spec["continuation"]:
                eq.plasma_psi = eq.create_psi_plasma_default(adaptive_centre=True)
                eq.solved = False

            for t_i in times:
                pf_i = load_pf_currents(float(t_i))
                ip_i = interp_at_time(ip_df, float(t_i), "ip")
                pk_i, src_used = _resolve_forward_profile_kwargs(
                    dump_profile_kwargs=profile_kwargs,
                    t_i=float(t_i),
                    source_requested=_src_req,
                )
                _src_used_rollup.add(src_used)
                if not mt_spec["continuation"]:
                    eq.plasma_psi = eq.create_psi_plasma_default(adaptive_centre=True)
                    eq.solved = False
                print(
                    f"[..] forward window sample t={float(t_i):.6f}s Ip={ip_i/1e6:.3f}MA "
                    f"profile_source={src_used} "
                    f"(timeout={mt_spec['per_time_timeout_s']}s, "
                    f"max_iter={mt_spec['max_solving_iterations']})",
                    flush=True,
                )
                result = _solve_forward_sample(
                    eq=eq,
                    tokamak=tokamak,
                    grid=grid,
                    solv=solv,
                    mt_spec=mt_spec,
                    profile_kwargs=pk_i,
                    t_i=float(t_i),
                    ip_i=float(ip_i),
                    pf_i=pf_i,
                    tokamak_pickle=tokamak_pickle,
                )
                entry = {
                    "t": float(t_i),
                    "ip": float(ip_i),
                    "status": result.get("status"),
                    "solve_mode": result.get("solve_mode"),
                    "iterations": result.get("iterations"),
                    "rel_change": result.get("rel_change"),
                    "duration_s": result.get("duration_s"),
                    "error": result.get("error"),
                    "profile_source_requested": _src_req,
                    "profile_source_used": src_used,
                }
                if result.get("ok"):
                    n_ok += 1
                    if pres.write_eq_frames:
                        # Child restore only copies plasma_psi — re-bind profiles.
                        _prof_i = ConstrainPaxisIp(
                            eq=eq, Ip=float(ip_i), **pk_i
                        )
                        tag = f"eq_t{float(t_i):.6f}".replace(".", "p")
                        png = _save_forward_png(
                            tokamak=tokamak,
                            eq=eq,
                            profiles=_prof_i,
                            out_path=frames_dir / f"{tag}.png",
                            title=(
                                f"Forward GS measured-PF replay "
                                f"t={float(t_i):.4f}s Ip={ip_i/1e6:.3f}MA"
                            ),
                            dpi=int(pres.gif_dpi),
                            figsize=(4.0, 8.0),
                            plot_style=_plot_style,
                        )
                        entry["frame_png"] = str(png.relative_to(HERE)).replace("\\", "/")
                        _live = _live_forward_lcfs(eq)
                        if _live is not None:
                            entry["lcfs_n"] = int(len(_live[0]))
                    print(
                        f"[OK] forward window sample t={float(t_i):.6f}s "
                        f"status={entry['status']} duration_s={result.get('duration_s')}",
                        flush=True,
                    )
                else:
                    n_skip += 1
                    print(
                        f"[SKIP] forward window sample t={float(t_i):.6f}s: {result.get('error')}",
                        flush=True,
                    )
                per_time.append(entry)

            (HERE / "presentation" / "forward_times.json").write_text(
                json.dumps(
                    {
                        **tb_meta,
                        "per_time": per_time,
                        "solve_mode": "forward_gs",
                        "n_ok": n_ok,
                        "n_skipped": n_skip,
                        "multitime_authority": mt_spec,
                        "profile_source_requested": _src_req,
                        "profile_sources_used": sorted(_src_used_rollup),
                        "note": (
                            "Multi-time forward uses measured PF/Ip at each window sample "
                            "(not Inverse dump currents). Default profiles freeze Inverse "
                            "dump paxis/α (forward_profile_source=inverse_dump_frozen); "
                            "optional profile_trajectory is declared authority only. "
                            "Plots use live Forward LCFS — never Inverse dump LCFS / Inverse "
                            "null targets (measured-PF Forward is not Inverse shape acceptance; "
                            "SN-vs-DN vs Inverse is expected). psi continuation from t0 "
                            "(unless continuation=false), max_solving_iterations + hard "
                            "per_time_timeout_s kill. Skipped times omit frames; never fabricate."
                        ),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            if pres.write_equilibrium_gifs:
                frames = sorted_frame_paths(frames_dir, "eq_t*.png")
                gif_rep = write_gif_from_pngs(
                    frames,
                    HERE / "presentation" / "forward_equilibria.gif",
                    fps=float(pres.gif_fps),
                )
                (HERE / "presentation" / "forward_gif_report.json").write_text(
                    json.dumps(gif_rep, indent=2) + "\n", encoding="utf-8"
                )
                if gif_rep.get("ok"):
                    print(
                        f"[OK] Wrote presentation/forward_equilibria.gif "
                        f"({gif_rep.get('n_frames')} frames)"
                    )
                else:
                    print(f"[WARN] forward GIF not written: {gif_rep.get('errors')}")
    except Exception as e:
        print(f"[WARN] multi-time forward presentation failed: {e}", flush=True)

    if _INTROSPECT_AVAILABLE:
        try:
            write_solver_introspection(
                HERE,
                execution_authority_bundle=ea,
                objects={
                    "tokamak": tokamak,
                    "eq": eq,
                    "profiles": profiles,
                    "solver": solver,
                },
            )
            print("[OK] Wrote solver_introspection/")
        except Exception as _e:
            print(f"[WARN] solver introspection failed: {_e}")

if __name__ == "__main__":
    main()
