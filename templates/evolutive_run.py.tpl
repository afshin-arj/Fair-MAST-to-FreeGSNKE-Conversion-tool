#!/usr/bin/env python3
# Generated FreeGSNKE evolutive forward solve (FAIR-MAST voltages)
#
# Author: © 2026 Afshin Arjhangmehr
#
# Uses freegsnke.nonlinear_solve.nl_solver + initialize_from_ICs + nlstepper
# with active_voltage_vec from:
#   - measured FAIR-MAST Level-2 voltages (primary drive for mapped channels)
#   - from_current_ohmic: V = sign*scale*I*R using FreeGSNKE coil_resist
#   - declared default_V=0 for MAST-U-only divertor circuits
# Profile alpha_m/alpha_n/fvac held from inverse IC; optional scale_paxis_with_ip.

from __future__ import annotations

import json
import math
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
        "linear_only",
        "plasma_resistivity_ohm_m",
        "max_solving_iterations",
        "max_mode_frequency",
    ]
    missing = [k for k in required if k not in obj]
    if missing:
        raise KeyError("evolutive_authority missing keys: " + ", ".join(missing))
    cover = bool(obj.get("cover_window", False))
    if (not cover) and ("n_steps" not in obj or obj["n_steps"] is None):
        raise KeyError(
            "evolutive_authority missing n_steps "
            "(required when cover_window is false)"
        )
    return obj


def _resolve_n_steps(ea_evolv: dict, t_start: float, t_end: float) -> dict:
    dt = float(ea_evolv["full_timestep_s"])
    span = float(t_end) - float(t_start)
    n_from_window = max(1, int(math.ceil(span / dt))) if span > 0.0 else 1
    cover = bool(ea_evolv.get("cover_window", False))
    max_steps = int(ea_evolv.get("max_steps", 50))
    n_override = ea_evolv.get("n_steps", None)
    if cover:
        if n_override is not None:
            n = int(n_override)
            mode = "n_steps_override"
        else:
            n = min(max_steps, n_from_window)
            mode = "cover_window"
    else:
        n = int(n_override)
        mode = "fixed_n_steps"
    return {
        "n_steps": int(n),
        "mode": mode,
        "full_timestep_s": dt,
        "t_start": float(t_start),
        "t_end": float(t_end),
        "window_span_s": float(span),
        "n_from_window": int(n_from_window),
        "max_steps": max_steps,
        "cover_window": cover,
    }


def _load_execution_authority_bundle() -> dict:
    bp = INPUTS / "execution_authority" / "execution_authority_bundle.json"
    return _load_json(bp)


def _load_voltage_map_resolved() -> dict:
    for cand in [
        HERE / "contracts" / "voltage_map.resolved.json",
        INPUTS / "voltage_map.resolved.json",
    ]:
        if cand.exists():
            return _load_json(cand)
    raise FileNotFoundError(
        "Missing voltage_map.resolved.json with machine_active_circuit_order "
        "(pipeline must snapshot voltage_map before evolutive execute)"
    )


def _load_voltage_order(vmap: dict) -> list:
    order = vmap.get("machine_active_circuit_order")
    if isinstance(order, list) and order:
        return [str(x) for x in order]
    raise FileNotFoundError("voltage_map.resolved.json missing machine_active_circuit_order")


def _ohmic_specs(vmap: dict) -> dict:
    """circuit_name -> spec for from_current_ohmic combines."""
    out = {}
    circuits = vmap.get("circuits") or {}
    for name, spec in circuits.items():
        if not isinstance(spec, dict):
            continue
        if str(spec.get("combine", "")) == "from_current_ohmic":
            out[str(name)] = spec
    return out


def _interp_series(t_abs: float, t: np.ndarray, y: np.ndarray, label: str) -> float:
    mask = np.isfinite(t) & np.isfinite(y)
    if int(mask.sum()) < 2:
        raise RuntimeError(
            "insufficient finite samples for " + label
            + " (cannot invent fill values)"
        )
    return float(np.interp(t_abs, t[mask], y[mask]))


def _interp_voltage_vec(
    t_abs: float,
    volt_df: pd.DataFrame,
    order: list,
    *,
    ohmic: dict,
    currents_df: pd.DataFrame | None,
    coil_resist: np.ndarray | None,
) -> np.ndarray:
    t = volt_df["time"].to_numpy(dtype=float)
    vec = np.zeros(len(order), dtype=float)
    for i, name in enumerate(order):
        if name in ohmic:
            if coil_resist is None or i >= len(coil_resist) or not np.isfinite(coil_resist[i]):
                raise RuntimeError(
                    "fail-closed: FreeGSNKE coil_resist unavailable for ohmic circuit "
                    + name
                    + " (from_current_ohmic requires machine R after load)"
                )
            if currents_df is None:
                raise RuntimeError(
                    "fail-closed: pf_currents.csv required for from_current_ohmic circuit "
                    + name
                )
            spec = ohmic[name]
            cur_name = str(spec.get("current_circuit", name))
            if cur_name not in currents_df.columns:
                raise KeyError(
                    "pf_currents.csv missing current_circuit column "
                    + cur_name
                    + " for ohmic circuit "
                    + name
                )
            scale = float(spec.get("scale", 1.0))
            sign = float(spec.get("sign", 1))
            t_i = currents_df["time"].to_numpy(dtype=float)
            i_y = currents_df[cur_name].to_numpy(dtype=float)
            i_val = _interp_series(t_abs, t_i, i_y, "current " + cur_name)
            r = float(coil_resist[i])
            if not (r > 0.0):
                raise RuntimeError(
                    "fail-closed: non-positive coil_resist for circuit "
                    + name
                    + " R="
                    + str(r)
                )
            vec[i] = sign * scale * i_val * r
            continue

        if name not in volt_df.columns:
            raise KeyError("pf_voltages.csv missing circuit column: " + name)
        y = volt_df[name].to_numpy(dtype=float)
        vec[i] = _interp_series(t_abs, t, y, "voltage " + name)
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
            "paxis": history["paxis"][i],
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
    linear_only = bool(ea_evolv["linear_only"])
    scale_paxis = bool(ea_evolv.get("scale_paxis_with_ip", False))
    eta = float(ea_evolv["plasma_resistivity_ohm_m"])
    max_iter = int(ea_evolv["max_solving_iterations"])
    max_mode_freq = float(ea_evolv["max_mode_frequency"])
    snap_every = int(ea_evolv.get("snapshot_equilibria_every_n", 5))
    min_dIy = ea_evolv.get("min_dIy_dI")
    # If presentation wants GIFs but authority left snapshots off, enable every step
    # (declared by presentation_authority.json — not a silent invent).
    try:
        from mast_freegsnke.equilibrium_presentation import try_load_presentation_authority
        _pres0 = try_load_presentation_authority(INPUTS)
        if _pres0 is not None and _pres0.write_equilibrium_gifs and snap_every <= 0:
            snap_every = 1
            print(
                "[INFO] presentation_authority.write_equilibrium_gifs=true "
                "→ enabling snapshot_equilibria_every_n=1 for GIF frames",
                flush=True,
            )
    except Exception as _pe:
        print(f"[WARN] presentation authority check failed: {_pe}", flush=True)

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

    vmap = _load_voltage_map_resolved()
    order = _load_voltage_order(vmap)
    ohmic = _ohmic_specs(vmap)

    volt_path = INPUTS / "pf_voltages.csv"
    if not volt_path.exists():
        raise FileNotFoundError(
            "Missing inputs/pf_voltages.csv — voltage_map must be applied before evolutive"
        )
    volt_df = pd.read_csv(volt_path)
    if "time" not in volt_df.columns:
        raise ValueError("pf_voltages.csv missing time column")

    currents_df = None
    if ohmic:
        cur_path = INPUTS / "pf_currents.csv"
        if not cur_path.exists():
            raise FileNotFoundError(
                "Missing inputs/pf_currents.csv required for from_current_ohmic circuits: "
                + ", ".join(sorted(ohmic.keys()))
            )
        currents_df = pd.read_csv(cur_path)

    ip_df = None
    if scale_paxis:
        ip_path = INPUTS / "ip.csv"
        if not ip_path.exists():
            raise FileNotFoundError(
                "scale_paxis_with_ip=true requires inputs/ip.csv (measured Ip)"
            )
        ip_df = pd.read_csv(ip_path)
        if "time" not in ip_df.columns:
            raise ValueError("ip.csv missing time column")
        # Prefer column named Ip / ip / plasma_current
        ip_col = None
        for cand in ("Ip", "ip", "plasma_current", "I_p"):
            if cand in ip_df.columns:
                ip_col = cand
                break
        if ip_col is None:
            non_time = [c for c in ip_df.columns if c != "time"]
            if len(non_time) == 1:
                ip_col = non_time[0]
            else:
                raise ValueError(
                    "ip.csv must have an Ip column for scale_paxis_with_ip "
                    "(found: " + ", ".join(ip_df.columns) + ")"
                )

    win = _load_json(INPUTS / "window.json")
    t_start = float(win["t_start"])
    t_end = float(win["t_end"])
    t0 = float(dump.get("t0", t_start))
    # Drive from formed-plasma t0 within the finalized window.
    t_drive0 = max(t0, t_start)
    if t_drive0 >= t_end:
        t_drive0 = t_start

    step_plan = _resolve_n_steps(ea_evolv, t_start, t_end)
    n_steps = int(step_plan["n_steps"])
    print(
        f"[INFO] evolutive step plan: mode={step_plan['mode']} n_steps={n_steps} "
        f"dt={full_dt}s window=[{t_start:.6f},{t_end:.6f}] "
        f"n_from_window={step_plan['n_from_window']} max_steps={step_plan['max_steps']}",
        flush=True,
    )

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
    paxis0 = float(pk["paxis"])
    alpha_m0 = float(pk["alpha_m"])
    alpha_n0 = float(pk["alpha_n"])
    Ip0 = float(pk["Ip"])
    profiles = ConstrainPaxisIp(
        eq=eq,
        paxis=paxis0,
        Ip=Ip0,
        fvac=float(dump["fvac"]),
        alpha_m=alpha_m0,
        alpha_n=alpha_n0,
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

    # Snapshot FreeGSNKE active coil resistances (same source nl_solver uses).
    coil_resist = np.asarray(
        stepping.evol_metal_curr.active_coil_resistances, dtype=float
    ).copy()
    if coil_resist.shape[0] != n_active or not np.all(np.isfinite(coil_resist)):
        raise RuntimeError(
            "fail-closed: evol_metal_curr.active_coil_resistances missing/invalid "
            f"(shape={coil_resist.shape}, finite={np.isfinite(coil_resist).sum()}/{coil_resist.size})"
        )
    if ohmic and not np.all(coil_resist > 0.0):
        raise RuntimeError(
            "fail-closed: non-positive FreeGSNKE coil_resist with from_current_ohmic circuits: "
            + str(coil_resist.tolist())
        )
    resist_snapshot = {
        "source": "nl_solver.evol_metal_curr.active_coil_resistances",
        "circuit_order": list(order),
        "coil_resist_ohm": coil_resist.tolist(),
        "ohmic_circuits": sorted(ohmic.keys()),
    }
    print(
        "[INFO] coil_resist_ohm=" + str({k: float(coil_resist[i]) for i, k in enumerate(order)}),
        flush=True,
    )

    stepping.initialize_from_ICs(eq, profiles)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "coil_resist_snapshot.json").write_text(
        json.dumps(resist_snapshot, indent=2) + "\n", encoding="utf-8"
    )

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
        "paxis": [],
    }
    coil_names = list(order)

    t_rel = 0.0
    for step in range(n_steps):
        t_abs = t_drive0 + t_rel
        if t_abs > t_end:
            print(f"[INFO] stopping early at step {step}: t_abs={t_abs:.6f} > t_end={t_end:.6f}")
            break
        vvec = _interp_voltage_vec(
            t_abs,
            volt_df,
            order,
            ohmic=ohmic,
            currents_df=currents_df,
            coil_resist=coil_resist,
        )
        profiles_parameters = None
        paxis_step = paxis0
        if scale_paxis:
            assert ip_df is not None
            t_ip = ip_df["time"].to_numpy(dtype=float)
            y_ip = ip_df[ip_col].to_numpy(dtype=float)
            ip_t = _interp_series(t_abs, t_ip, y_ip, "Ip")
            if not (abs(Ip0) > 0.0):
                raise RuntimeError(
                    "fail-closed: scale_paxis_with_ip requires non-zero Ip0 from inverse IC"
                )
            paxis_step = paxis0 * (ip_t / Ip0)
            profiles_parameters = {
                "paxis": float(paxis_step),
                "alpha_m": alpha_m0,
                "alpha_n": alpha_n0,
            }

        print(
            f"Step {step}/{n_steps - 1}  t_abs={t_abs:.6f}  linear_only={linear_only} "
            f"scale_paxis={scale_paxis} paxis={paxis_step:.6g}",
            flush=True,
        )
        step_ok = True
        try:
            stepping.nlstepper(
                active_voltage_vec=vvec,
                profiles_parameters=profiles_parameters,
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
            history["paxis"].append(float(paxis_step))
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
        history["paxis"].append(float(paxis_step))

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

    n_measured = sum(
        1
        for name in order
        if str((vmap.get("circuits") or {}).get(name, {}).get("combine", ""))
        in ("identity", "sum", "mean")
    )
    n_ohmic = len(ohmic)
    n_zero = len(order) - n_measured - n_ohmic

    meta = {
        "t_drive0": t_drive0,
        "t_start": t_start,
        "t_end": t_end,
        "n_steps_requested": n_steps,
        "n_steps_recorded": len(history["t_abs"]),
        "step_plan": step_plan,
        "full_timestep_s": full_dt,
        "linear_only": linear_only,
        "scale_paxis_with_ip": scale_paxis,
        "plasma_resistivity_ohm_m": eta,
        "max_solving_iterations": max_iter,
        "active_circuit_order": coil_names,
        "coil_resist_ohm": resist_snapshot,
        "drive_policy": {
            "n_measured_fairmast_V": n_measured,
            "n_from_current_ohmic": n_ohmic,
            "n_declared_zero_V": n_zero,
            "ohmic_circuits": sorted(ohmic.keys()),
            "machine_circuits_without_fairmast_drive": vmap.get(
                "machine_circuits_without_fairmast_drive"
            ),
        },
        "profile_source": "inverse_dump_IC",
        "profile_policy": {
            "alpha_m_alpha_n_fvac": "held_from_inverse_IC",
            "scale_paxis_with_ip": scale_paxis,
            "paxis0": paxis0,
            "Ip0": Ip0,
        },
        "limitations": [
            "FAIR-MAST Level-2 supplies measured voltages p1/p2/p4/p5 (primary drive)",
            "P6 (and any from_current_ohmic) uses V=I×R with FreeGSNKE coil_resist — not invented R",
            "MAST-U-only divertor circuits (D1–D7/Dp) use declared default_V=0 (no classic-MAST FAIR-MAST drive)",
            "Mismatch is FreeGSNKE structural coils vs classic MAST PF set — not missing FAIR-MAST voltages",
            (
                "paxis scaled with measured Ip(t)/Ip(t0) (declared law)"
                if scale_paxis
                else "Profile parameters held from IC (scale_paxis_with_ip=false)"
            ),
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
        fig.suptitle("Evolutive forward (FAIR-MAST voltages + ohmic I×R)")
        fig.tight_layout()
        fig.savefig(OUT / "history_overview.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

    # Stitch evolutive equilibrium GIF from step snapshots (when enabled)
    try:
        from mast_freegsnke.equilibrium_presentation import (
            sorted_frame_paths,
            try_load_presentation_authority,
            write_gif_from_pngs,
        )
        _pres = try_load_presentation_authority(INPUTS)
        if _pres is not None and _pres.write_equilibrium_gifs:
            _frames = sorted_frame_paths(OUT, "eq_snapshot_step*.png")
            _gif_rep = write_gif_from_pngs(
                _frames,
                OUT / "evolutive_equilibria.gif",
                fps=float(_pres.gif_fps),
            )
            (OUT / "evolutive_gif_report.json").write_text(
                json.dumps(_gif_rep, indent=2) + "\n", encoding="utf-8"
            )
            if _gif_rep.get("ok"):
                print(
                    f"[OK] Wrote evolutive/evolutive_equilibria.gif "
                    f"({_gif_rep.get('n_frames')} frames)",
                    flush=True,
                )
            else:
                print(f"[WARN] evolutive GIF not written: {_gif_rep.get('errors')}", flush=True)
    except Exception as _ge:
        print(f"[WARN] evolutive GIF stage failed: {_ge}", flush=True)

    n_ok = int(sum(1 for x in history["step_ok"] if x))
    if n_ok < 1:
        raise RuntimeError(
            "Evolutive forward recorded zero successful steps — see logs and evolutive/evolutive_meta.json"
        )
    print(f"[OK] evolutive forward: {n_ok} successful steps -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
