#!/usr/bin/env python3
# Generated FreeGSNKE static forward replay solve
#
# Author: © 2026 Afshin Arjhangmehr

from pathlib import Path
import json
import pickle
import numpy as np
import matplotlib.pyplot as plt

from freegsnke import build_machine
from freegsnke import equilibrium_update
from freegsnke.jtor_update import ConstrainPaxisIp
from freegsnke import GSstaticsolver

HERE = Path(__file__).resolve().parent
MACHINE = Path({machine_dir!r})
DUMP = HERE / "inverse_dump.pkl"
ACTIVE_CIRCUITS = ["P2_inner","P2_outer","P3","P4","P5","P6","Solenoid"]


def _load_execution_authority_bundle_fallback() -> dict:
    bp = HERE / "inputs" / "execution_authority" / "execution_authority_bundle.json"
    if not bp.exists():
        raise FileNotFoundError("Missing execution authority bundle (fallback): " + str(bp))
    obj = json.loads(bp.read_text())
    if not isinstance(obj, dict):
        raise ValueError("Execution authority bundle must be a JSON object")
    return obj

def set_active_currents(tokamak, dump):
    cur = dump.get("coil_currents", {})
    for cname, coil in getattr(tokamak, "coils", []):
        if cname in ACTIVE_CIRCUITS and cname in cur and hasattr(coil, "current"):
            coil.current = float(cur[cname])

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
    set_active_currents(tokamak, dump)

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
    solver.solve(
        eq=eq,
        profiles=profiles,
        constrain=None,
        target_relative_tolerance=float(solv["forward_target_relative_tolerance"]),
        verbose=True,
    )

    fig, ax = plt.subplots(1,1, figsize=(6,10), dpi=140)
    tokamak.plot(axis=ax, show=False)
    eq.plot(axis=ax, show=False)
    ax.set_aspect("equal"); ax.grid(alpha=0.3)
    t0 = dump.get("t0"); Ip = dump.get("Ip")
    if t0 is not None and Ip is not None:
        ax.set_title(f"Forward replay (t0={t0:.3f}s, Ip={Ip/1e6:.3f}MA)")
    else:
        ax.set_title("Forward replay")
    fig.tight_layout()
    fig.savefig(HERE/"forward_equilibrium.png", dpi=250, bbox_inches="tight")
    print("Saved forward_equilibrium.png")

if __name__ == "__main__":
    main()
