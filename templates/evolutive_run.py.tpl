#!/usr/bin/env python3
# Generated FreeGSNKE evolutive forward solve (FAIR-MAST voltages)
#
# Author: © 2026 Afshin Arjhangmehr
#
# Uses freegsnke.nonlinear_solve.nl_solver + initialize_from_ICs + nlstepper
# with active_voltage_vec interpolated from mapped FAIR-MAST voltages.
# Profile parameters are held from the inverse IC (never invented).

from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from freegsnke import build_machine
from freegsnke import equilibrium_update
from freegsnke.jtor_update import ConstrainPaxisIp
from freegsnke import GSstaticsolver
from freegsnke import nonlinear_solve

HERE = Path(__file__).resolve().parent
MACHINE = Path(__MACHINE_DIR_REPR__)
INPUTS = HERE / "inputs"
DUMP = HERE / "inverse_dump.pkl"
OUT = HERE / "evolutive"


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError("Missing required file: " + str(path))
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Expected JSON object: " + str(path))
    return obj


def _load_evolutive_authority() -> dict:
    """Fail-closed: evolutive numerics must be declared (no hidden defaults)."""
    bp = INPUTS / "evolutive_authority" / "evolutive_authority.json"
    obj = _load_json(bp)
    required = [
        "full_timestep_s",
        "n_steps",
        "linear_only",
        "plasma_resistivity_ohm_m",
        "max_solving_iterations",
        "max_mode_frequency",
    ]
    missing = [k for k in required if k not in obj]
    if missing:
        raise KeyError("evolutive_authority missing keys: " + ", ".join(missing))
    return obj


def _load_execution_authority_bundle() -> dict:
    bp = INPUTS / "execution_authority" / "execution_authority_bundle.json"
    return _load_json(bp)


def _load_voltage_order() -> list:
    """Active circuit order from snapshotted voltage_map (must match nl_solver vector)."""
    for cand in [
        HERE / "contracts" / "voltage_map.resolved.json",
        INPUTS / "voltage_map.resolved.json",
    ]:
        if cand.exists():
            obj = _load_json(cand)
            order = obj.get("machine_active_circuit_order")
            if isinstance(order, list) and order:
                return [str(x) for x in order]
    raise FileNotFoundError(
        "Missing voltage_map.resolved.json with machine_active_circuit_order "
        "(pipeline must snapshot voltage_map before evolutive execute)"
    )


def _interp_voltage_vec(t_abs: float, volt_df: pd.DataFrame, order: list) -> np.ndarray:
    t = volt_df["time"].to_numpy(dtype=float)
    vec = np.zeros(len(order), dtype=float)
    for i, name in enumerate(order):
        if name not in volt_df.columns:
            raise KeyError("pf_voltages.csv missing circuit column: " + name)
        y = volt_df[name].to_numpy(dtype=float)
        mask = np.isfinite(t) & np.isfinite(y)
        if int(mask.sum()) < 2:
            raise RuntimeError(
                "insufficient finite voltage samples for circuit " + name
                + " (cannot invent fill values)"
            )
        vec[i] = float(np.interp(t_abs, t[mask], y[mask]))
    return vec


def _write_history_csv(path: Path, history: dict, coil_names: list) -> None:
    rows = []
    for i in range(len(history["t_abs"])):
        row = {
            "t_abs": history["t_abs"][i],
            "t_rel": history["t_rel"][i],
            "Ip": history["Ip"][i],
            "Raxis": history["Raxis"][i],
            "Zaxis": history["Zaxis"][i],
            "elongation": history["elongation"][i],
            "triangularity": history["triangularity"][i],
            "step_ok": history["step_ok"][i],
        }
        for j, name in enumerate(coil_names):
            vlist = history["voltages"][i]
            row["V_" + name] = vlist[j] if j < len(vlist) else float("nan")
        for j, name in enumerate(coil_names):
            clist = history["currents"][i]
            row["I_" + name] = clist[j] if j < len(clist) else float("nan")
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False)


def _control_coil_names(tokamak) -> list:
    names = []
    for name, coil in getattr(tokamak, "coils", []):
        if hasattr(coil, "control") and coil.control:
            names.append(name)
    return names


def _set_currents(tokamak, currents: dict) -> None:
    for name, coil in getattr(tokamak, "coils", []):
        if name in currents and hasattr(coil, "current"):
            coil.current = float(currents[name])


def main() -> None:
    ea_evolv = _load_evolutive_authority()
    full_dt = float(ea_evolv["full_timestep_s"])
    n_steps = int(ea_evolv["n_steps"])
    linear_only = bool(ea_evolv["linear_only"])
    eta = float(ea_evolv["plasma_resistivity_ohm_m"])
    max_iter = int(ea_evolv["max_solving_iterations"])
    max_mode_freq = float(ea_evolv["max_mode_frequency"])
    snap_every = int(ea_evolv.get("snapshot_equilibria_every_n", 5))
    min_dIy = ea_evolv.get("min_dIy_dI")

    if not DUMP.exists():
        raise FileNotFoundError(
            "Missing inverse_dump.pkl — run inverse first so evolutive has an IC "
            "(profiles held from IC; alpha_m/n are never invented here)."
        )
    with open(DUMP, "rb") as f:
        dump = pickle.load(f)

    ea = dump.get("execution_authority_bundle")
    if ea is None:
        ea = _load_execution_authority_bundle()
    grid = ea["grid"]

    order = _load_voltage_order()
    volt_path = INPUTS / "pf_voltages.csv"
    if not volt_path.exists():
        raise FileNotFoundError(
            "Missing inputs/pf_voltages.csv — voltage_map must be applied before evolutive"
        )
    volt_df = pd.read_csv(volt_path)
    if "time" not in volt_df.columns:
        raise ValueError("pf_voltages.csv missing time column")

    win = _load_json(INPUTS / "window.json")
    t_start = float(win["t_start"])
    t_end = float(win["t_end"])
    t0 = float(dump.get("t0", t_start))
    # Drive from formed-plasma t0 within the finalized window.
    t_drive0 = max(t0, t_start)
    if t_drive0 >= t_end:
        t_drive0 = t_start

    tokamak = build_machine.tokamak(
        active_coils_path=str(MACHINE / "active_coils.pickle"),
        passive_coils_path=str(MACHINE / "passive_coils.pickle"),
        limiter_path=str(MACHINE / "limiter.pickle"),
        wall_path=str(MACHINE / "wall.pickle"),
        magnetic_probe_path=(
            str(HERE / "magnetic_probes.pickle")
            if (HERE / "magnetic_probes.pickle").exists()
            else None
        ),
    )
    machine_order = _control_coil_names(tokamak)
    if machine_order != order:
        raise RuntimeError(
            "voltage_map machine_active_circuit_order does not match FreeGSNKE "
            "control coils after load.\n"
            "  map: " + str(order) + "\n"
            "  tok: " + str(machine_order) + "\n"
            "Update configs/voltage_map.json to match active_coils.pickle (fail-closed)."
        )

    _set_currents(tokamak, dump.get("coil_currents") or {})

    eq = equilibrium_update.Equilibrium(
        tokamak=tokamak,
        Rmin=float(grid["Rmin"]),
        Rmax=float(grid["Rmax"]),
        Zmin=float(grid["Zmin"]),
        Zmax=float(grid["Zmax"]),
        nx=int(grid["nx"]),
        ny=int(grid["ny"]),
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

    # Restore plasma_psi from inverse if present
    if dump.get("plasma_psi") is not None:
        try:
            eq.plasma_psi = np.asarray(dump["plasma_psi"], dtype=float)
        except Exception as e:
            print("[WARN] could not restore plasma_psi from dump:", e)

    GSStaticSolver = GSstaticsolver.NKGSsolver(eq)
    # Required: nl_solver needs a converged GS IC (core_mask); restoring plasma_psi
    # alone is not enough when coil currents / profiles are reapplied.
    print("[INFO] Static GS solve for evolutive IC...", flush=True)
    GSStaticSolver.solve(
        eq=eq,
        profiles=profiles,
        constrain=None,
        target_relative_tolerance=float(ea["solver"]["forward_target_relative_tolerance"]),
        verbose=0,
    )

    nl_kwargs = dict(
        eq=eq,
        profiles=profiles,
        GSStaticSolver=GSStaticSolver,
        full_timestep=full_dt,
        plasma_resistivity=eta,
        max_mode_frequency=max_mode_freq,
    )
    if min_dIy is not None:
        nl_kwargs["min_dIy_dI"] = float(min_dIy)

    print(f"[INFO] Instantiating nl_solver (dt={full_dt}, eta={eta}, min_dIy_dI={min_dIy})...", flush=True)
    stepping = nonlinear_solve.nl_solver(**nl_kwargs)
    print(f"[INFO] nl_solver ready; n_active={stepping.evol_metal_curr.n_active_coils}", flush=True)
    n_active = int(stepping.evol_metal_curr.n_active_coils)
    if n_active != len(order):
        raise RuntimeError(
            f"n_active_coils={n_active} != len(voltage_map order)={len(order)}"
        )

    stepping.initialize_from_ICs(eq, profiles)

    OUT.mkdir(parents=True, exist_ok=True)
    history = {
        "t_abs": [],
        "t_rel": [],
        "Ip": [],
        "Raxis": [],
        "Zaxis": [],
        "elongation": [],
        "triangularity": [],
        "step_ok": [],
        "voltages": [],
        "currents": [],
    }
    coil_names = list(order)

    t_rel = 0.0
    for step in range(n_steps):
        t_abs = t_drive0 + t_rel
        if t_abs > t_end:
            print(f"[INFO] stopping early at step {step}: t_abs={t_abs:.6f} > t_end={t_end:.6f}")
            break
        vvec = _interp_voltage_vec(t_abs, volt_df, order)
        print(f"Step {step}/{n_steps - 1}  t_abs={t_abs:.6f}  linear_only={linear_only}", flush=True)
        step_ok = True
        try:
            stepping.nlstepper(
                active_voltage_vec=vvec,
                linear_only=linear_only,
                verbose=False,
                max_solving_iterations=max_iter,
            )
        except Exception as e:
            step_ok = False
            print(f"[FAIL] nlstepper error at step {step}: {type(e).__name__}: {e}")
            history["t_abs"].append(t_abs)
            history["t_rel"].append(t_rel)
            history["Ip"].append(float("nan"))
            history["Raxis"].append(float("nan"))
            history["Zaxis"].append(float("nan"))
            history["elongation"].append(float("nan"))
            history["triangularity"].append(float("nan"))
            history["step_ok"].append(False)
            history["voltages"].append(vvec.tolist())
            history["currents"].append([])
            break

        t_rel += float(getattr(stepping, "dt_step", full_dt))
        # Record post-step state
        try:
            opt = stepping.eq1.opt[0]
            Raxis, Zaxis = float(opt[0]), float(opt[1])
        except Exception:
            Raxis, Zaxis = float("nan"), float("nan")
        try:
            elong = float(stepping.eq1.geometricElongation())
        except Exception:
            elong = float("nan")
        try:
            tri = float(stepping.eq1.triangularity())
        except Exception:
            tri = float("nan")
        try:
            Ip = float(stepping.currents_vec[-1] * stepping.plasma_norm_factor)
        except Exception:
            Ip = float("nan")
        try:
            currents = np.asarray(stepping.currents_vec[:n_active], dtype=float).tolist()
        except Exception:
            currents = []

        history["t_abs"].append(t_abs)
        history["t_rel"].append(t_rel)
        history["Ip"].append(Ip)
        history["Raxis"].append(Raxis)
        history["Zaxis"].append(Zaxis)
        history["elongation"].append(elong)
        history["triangularity"].append(tri)
        history["step_ok"].append(step_ok)
        history["voltages"].append(vvec.tolist())
        history["currents"].append(currents)

        # Crash-safe incremental history (nlstepper can hang after linearization departure)
        _write_history_csv(OUT / "history.csv", history, coil_names)
        print(f"[OK] step {step} recorded  Ip={Ip}  Raxis={Raxis}  Zaxis={Zaxis}", flush=True)

        if snap_every > 0 and (step % snap_every == 0):
            try:
                fig, ax = plt.subplots(1, 1, figsize=(4, 8), dpi=100)
                stepping.eq1.plot(axis=ax, show=False)
                tokamak.plot(axis=ax, show=False)
                ax.set_title(f"evolutive step {step}  t={t_abs:.4f}s")
                fig.tight_layout()
                fig.savefig(OUT / f"eq_snapshot_step{step:04d}.png", dpi=120, bbox_inches="tight")
                plt.close(fig)
            except Exception as e:
                print(f"[WARN] snapshot failed at step {step}: {e}", flush=True)

    # Final CSV + meta (history already flushed incrementally)
    hist_df = pd.read_csv(OUT / "history.csv") if (OUT / "history.csv").exists() else pd.DataFrame()
    if hist_df.empty and history["t_abs"]:
        _write_history_csv(OUT / "history.csv", history, coil_names)
        hist_df = pd.read_csv(OUT / "history.csv")

    meta = {
        "t_drive0": t_drive0,
        "t_start": t_start,
        "t_end": t_end,
        "n_steps_requested": n_steps,
        "n_steps_recorded": len(history["t_abs"]),
        "full_timestep_s": full_dt,
        "linear_only": linear_only,
        "plasma_resistivity_ohm_m": eta,
        "max_solving_iterations": max_iter,
        "active_circuit_order": coil_names,
        "profile_source": "inverse_dump_IC",
        "limitations": [
            "MAST-U-like FreeGSNKE structural machine; classic MAST voltages mapped via voltage_map",
            "Missing voltage channels use declared default_V=0",
            "Profile parameters held from IC (not time-evolved from FAIR-MAST)",
        ],
    }
    (OUT / "evolutive_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    # Quick plots
    if len(hist_df) > 0:
        fig, axs = plt.subplots(2, 2, figsize=(10, 8), dpi=120)
        axs[0, 0].plot(hist_df["t_abs"], hist_df["Ip"])
        axs[0, 0].set_ylabel("Ip [A]"); axs[0, 0].set_xlabel("t [s]"); axs[0, 0].grid(True)
        axs[0, 1].plot(hist_df["t_abs"], hist_df["Raxis"], label="R")
        axs[0, 1].plot(hist_df["t_abs"], hist_df["Zaxis"], label="Z")
        axs[0, 1].legend(); axs[0, 1].set_xlabel("t [s]"); axs[0, 1].grid(True)
        axs[0, 1].set_ylabel("axis [m]")
        axs[1, 0].plot(hist_df["t_abs"], hist_df["elongation"])
        axs[1, 0].set_ylabel("elongation"); axs[1, 0].set_xlabel("t [s]"); axs[1, 0].grid(True)
        axs[1, 1].plot(hist_df["t_abs"], hist_df["triangularity"])
        axs[1, 1].set_ylabel("triangularity"); axs[1, 1].set_xlabel("t [s]"); axs[1, 1].grid(True)
        fig.suptitle("Evolutive forward (FAIR-MAST voltages)")
        fig.tight_layout()
        fig.savefig(OUT / "history_overview.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

    n_ok = int(sum(1 for x in history["step_ok"] if x))
    if n_ok < 1:
        raise RuntimeError(
            "Evolutive forward recorded zero successful steps — see logs and evolutive/evolutive_meta.json"
        )
    print(f"[OK] evolutive forward: {n_ok} successful steps -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
