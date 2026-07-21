#!/usr/bin/env python3
# Generated FreeGSNKE static forward replay solve (+ multi-time window frames/GIF)
#
# Author: © 2026 Afshin Arjhangmehr

from pathlib import Path
import json
import pickle
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


def main():
    with open(DUMP, "rb") as f:
        dump = pickle.load(f)

    ea = dump.get("execution_authority_bundle")
    if ea is None:
        ea = _load_execution_authority_bundle_fallback()
    grid = ea["grid"]
    solv = ea["solver"]

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
            for t_i in times:
                pf_i = load_pf_currents(float(t_i))
                ip_i = interp_at_time(ip_df, float(t_i), "ip")
                set_active_currents(tokamak, pf_i)
                profiles_i = ConstrainPaxisIp(
                    eq=eq,
                    paxis=float(pk["paxis"]),
                    Ip=float(ip_i),
                    fvac=float(dump["fvac"]),
                    alpha_m=float(pk["alpha_m"]),
                    alpha_n=float(pk["alpha_n"]),
                )
                eq.plasma_psi = eq.create_psi_plasma_default(adaptive_centre=True)
                eq.solved = False
                solver.solve(
                    eq=eq,
                    profiles=profiles_i,
                    constrain=None,
                    target_relative_tolerance=float(solv["forward_target_relative_tolerance"]),
                    verbose=False,
                )
                entry = {"t": float(t_i), "ip": float(ip_i), "status": "ok"}
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
                per_time.append(entry)
                print(f"[OK] forward window sample t={float(t_i):.6f}s Ip={ip_i/1e6:.3f}MA", flush=True)

            (HERE / "presentation" / "forward_times.json").write_text(
                json.dumps({**tb_meta, "per_time": per_time, "solve_mode": "forward_gs"}, indent=2)
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
