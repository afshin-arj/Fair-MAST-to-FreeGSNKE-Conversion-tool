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
    for k in ["grid", "profile", "boundary", "solver"]:
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

from freegsnke import build_machine
from freegsnke import equilibrium_update
from freegsnke.jtor_update import ConstrainPaxisIp
from freegsnke import GSstaticsolver
from freegsnke.inverse import Inverse_optimizer

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
MACHINE = Path({machine_dir!r})

def choose_formed_plasma_time(ip_df: pd.DataFrame, frac: float = {formed_frac}):
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
    df = pd.read_csv(INPUTS / "pf_currents.csv")
    out = {}
    for c in ["P2_inner","P2_outer","P3","P4","P5","P6","Solenoid"]:
        if c in df.columns and np.isfinite(df[c]).any():
            out[c] = interp_at_time(df, t0, c)
        else:
            out[c] = 0.0
    return out

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
    t0, ip0, ip_max = choose_formed_plasma_time(ip_df, frac={formed_frac})
    print(f"Selected formed-plasma time t0={{t0:.6f}} s  Ip={{ip0/1e6:.3f}} MA")

    tokamak = build_machine.tokamak(
        active_coils_path=str(MACHINE / "active_coils.pickle"),
        passive_coils_path=str(MACHINE / "passive_coils.pickle"),
        limiter_path=str(MACHINE / "limiter.pickle"),
        wall_path=str(MACHINE / "wall.pickle"),
        magnetic_probe_path=str(MACHINE / "magnetic_probes.pickle") if (MACHINE / "magnetic_probes.pickle").exists() else None,
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

if __name__ == "__main__":
    main()
