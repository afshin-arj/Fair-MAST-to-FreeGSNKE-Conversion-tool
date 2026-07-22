#!/usr/bin/env python3
# Generated FreeGSNKE static forward replay solve (+ multi-time window frames/GIF)
#
# Author: © 2026 Afshin Arjhangmehr

from pathlib import Path
import json
import multiprocessing as _mp
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
    for cname, coil in getattr(tokamak, "coils", []):
        if cname in ACTIVE_CIRCUITS and cname in currents_dict and hasattr(coil, "current"):
            coil.current = float(currents_dict[cname])


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

    fig, ax = plt.subplots(1, 1, figsize=(6, 10), dpi=140)
    tokamak.plot(axis=ax, show=False)
    eq.plot(axis=ax, show=False)
    ax.set_aspect("equal"); ax.grid(alpha=0.3)
    t0 = dump.get("t0"); Ip = dump.get("Ip")
    if t0 is not None and Ip is not None:
        ax.set_title(f"Forward replay (t0={t0:.3f}s, Ip={Ip/1e6:.3f}MA)")
    else:
        ax.set_title("Forward replay")
    fig.tight_layout()
    fig.savefig(HERE / "forward_equilibrium.png", dpi=250, bbox_inches="tight")
    plt.close(fig)
    print("Saved forward_equilibrium.png")

    # Multi-time forward GS across formed-plasma window → frames + GIF
    # Hard per-sample kill (same FreeGSNKE hang mode as inverse multi-time).
    try:
        from mast_freegsnke.equilibrium_presentation import (
            save_equilibrium_png,
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
            # Continue from the t0 forward solution (cold-start each sample can hang).
            if not mt_spec["continuation"]:
                eq.plasma_psi = eq.create_psi_plasma_default(adaptive_centre=True)
                eq.solved = False

            for t_i in times:
                pf_i = load_pf_currents(float(t_i))
                ip_i = interp_at_time(ip_df, float(t_i), "ip")
                if not mt_spec["continuation"]:
                    eq.plasma_psi = eq.create_psi_plasma_default(adaptive_centre=True)
                    eq.solved = False
                print(
                    f"[..] forward window sample t={float(t_i):.6f}s Ip={ip_i/1e6:.3f}MA "
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
                    profile_kwargs=profile_kwargs,
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
                }
                if result.get("ok"):
                    n_ok += 1
                    if pres.write_eq_frames:
                        tag = f"eq_t{float(t_i):.6f}".replace(".", "p")
                        png = save_equilibrium_png(
                            tokamak=tokamak,
                            eq=eq,
                            out_path=frames_dir / f"{tag}.png",
                            title=f"Forward GS  t={float(t_i):.4f}s  Ip={ip_i/1e6:.3f}MA",
                            dpi=int(pres.gif_dpi),
                        )
                        entry["frame_png"] = str(png.relative_to(HERE)).replace("\\", "/")
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
                        "note": (
                            "Multi-time forward uses measured PF/Ip at each window sample, "
                            "psi continuation from t0 (unless continuation=false), "
                            "max_solving_iterations + hard per_time_timeout_s kill. "
                            "Skipped times omit frames; never fabricate equilibria."
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
