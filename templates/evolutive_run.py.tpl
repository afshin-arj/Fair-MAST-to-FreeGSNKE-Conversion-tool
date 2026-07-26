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
# Profile: ADR-004 trajectory overrides IC hold / scale_paxis_with_ip when present.

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
# Optional overrides for plan-driven A/B evolutive (pipeline sets env; default = measured V).
import os as _os

OUT = Path(
    _os.environ.get("MAST_FREEGSNKE_EVOLUTIVE_OUT")
    or str(HERE / "evolutive")
)
_VOLT_ENV = _os.environ.get("MAST_FREEGSNKE_EVOLUTIVE_VOLTAGES")
VOLT_CSV = Path(_VOLT_ENV) if _VOLT_ENV else (INPUTS / "pf_voltages.csv")


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
    max_steps = int(ea_evolv.get("max_steps", 100))
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


def _arm_step_watchdog(timeout_s: float, step: int):
    """Hard-kill the process if nlstepper hangs in native code (Windows).

    threading.Timer can call os._exit even while FreeGSNKE is inside C/Fortran;
    soft Exception handling cannot escape that hang.
    """
    import os
    import threading

    def _boom() -> None:
        print(
            f"[TIMEOUT] evolutive nlstepper step {step} exceeded "
            f"per_step_timeout_s={timeout_s} — process hard-killed "
            f"(partial history.csv retained if flushed)",
            flush=True,
        )
        os._exit(124)

    t = threading.Timer(float(timeout_s), _boom)
    t.daemon = True
    t.start()
    return t


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


def _try_load_profile_trajectory():
    """ADR-004: declared time-dependent ConstrainPaxisIp knobs (never invent)."""
    try:
        from mast_freegsnke.profile_trajectory import try_load_built_trajectory, interpolate_profile_at
    except Exception as e:
        print(f"[WARN] profile_trajectory import failed: {e}", flush=True)
        return None, None
    traj = try_load_built_trajectory(INPUTS)
    if traj is None:
        return None, None
    return traj, interpolate_profile_at


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
    per_step_timeout_s = float(ea_evolv.get("per_step_timeout_s", 180.0))
    if not (per_step_timeout_s > 0.0):
        raise ValueError("evolutive_authority.per_step_timeout_s must be > 0")
    abort_ip_frac = ea_evolv.get("abort_when_ip_below_measured_frac", 0.25)
    if abort_ip_frac is not None:
        abort_ip_frac = float(abort_ip_frac)
        if not (0.0 < abort_ip_frac < 1.0):
            raise ValueError(
                "evolutive_authority.abort_when_ip_below_measured_frac must be in (0,1) or null"
            )
    ic_coil_src = str(ea_evolv.get("ic_coil_currents", "measured_pf")).strip().lower()
    if ic_coil_src not in {"measured_pf", "inverse_dump"}:
        raise ValueError(
            "evolutive_authority.ic_coil_currents must be 'measured_pf' or 'inverse_dump' "
            f"(got {ic_coil_src!r})"
        )
    clamp_ip = bool(ea_evolv.get("clamp_ip_to_measured", True))
    abort_axis_drift_m = ea_evolv.get("abort_when_axis_drift_m", 0.12)
    if abort_axis_drift_m is not None:
        abort_axis_drift_m = float(abort_axis_drift_m)
        if not (abort_axis_drift_m > 0.0):
            raise ValueError(
                "evolutive_authority.abort_when_axis_drift_m must be > 0 or null"
            )
    traj, interpolate_profile_at = _try_load_profile_trajectory()
    use_trajectory = traj is not None
    if use_trajectory and scale_paxis:
        print(
            "[INFO] profile_trajectory present → overrides scale_paxis_with_ip "
            "(ADR-004 declared precedence)",
            flush=True,
        )
        scale_paxis = False
    if use_trajectory:
        print(
            f"[INFO] profile_trajectory: status=ok knots={len(traj.knots)} "
            f"fit_mode={traj.fit_mode_used} interp={traj.interpolation} "
            f"sha256={traj.content_sha256()[:12]}…",
            flush=True,
        )
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

    volt_path = VOLT_CSV
    if not volt_path.exists():
        raise FileNotFoundError(
            "Missing voltage CSV for evolutive: "
            + str(volt_path)
            + " — voltage_map must be applied (or set MAST_FREEGSNKE_EVOLUTIVE_VOLTAGES)"
        )
    volt_df = pd.read_csv(volt_path)
    if "time" not in volt_df.columns:
        raise ValueError(str(volt_path.name) + " missing time column")

    currents_df = None
    need_currents = bool(ohmic) or ic_coil_src == "measured_pf"
    if need_currents:
        cur_path = INPUTS / "pf_currents.csv"
        if not cur_path.exists():
            raise FileNotFoundError(
                "Missing inputs/pf_currents.csv required for "
                + (
                    "from_current_ohmic / ic_coil_currents=measured_pf: "
                    + ", ".join(sorted(ohmic.keys()))
                    if ohmic
                    else "ic_coil_currents=measured_pf"
                )
            )
        currents_df = pd.read_csv(cur_path)
        if "time" not in currents_df.columns:
            raise ValueError("pf_currents.csv missing time column")

    ip_df = None
    ip_col = None
    # Measured Ip for scale_paxis, clamp_ip_to_measured, and/or abort gate.
    if scale_paxis or clamp_ip or abort_ip_frac is not None:
        ip_path = INPUTS / "ip.csv"
        if not ip_path.exists():
            if scale_paxis or clamp_ip:
                raise FileNotFoundError(
                    "scale_paxis_with_ip / clamp_ip_to_measured require inputs/ip.csv "
                    "(measured Ip from FAIR-MAST)"
                )
            print(
                "[WARN] abort_when_ip_below_measured_frac set but inputs/ip.csv missing "
                "— Ip-collapse soft-stop disabled for this run",
                flush=True,
            )
            abort_ip_frac = None
        else:
            ip_df = pd.read_csv(ip_path)
            if "time" not in ip_df.columns:
                raise ValueError("ip.csv missing time column")
            # Prefer column named Ip / ip / plasma_current
            for cand in ("Ip", "ip", "plasma_current", "I_p"):
                if cand in ip_df.columns:
                    ip_col = cand
                    break
            if ip_col is None:
                non_time = [c for c in ip_df.columns if c != "time"]
                if len(non_time) == 1:
                    ip_col = non_time[0]
                elif scale_paxis or clamp_ip:
                    raise ValueError(
                        "ip.csv must have an Ip column for scale_paxis / clamp_ip "
                        "(found: " + ", ".join(ip_df.columns) + ")"
                    )
                else:
                    print(
                        "[WARN] ip.csv has no Ip column — Ip-collapse soft-stop disabled",
                        flush=True,
                    )
                    abort_ip_frac = None
                    ip_df = None

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

    # IC coil currents: measured_pf keeps V≈IR at t_drive0 (voltage-driven science).
    # inverse_dump keeps shape-optimised currents (can disagree with measured PF).
    ic_currents: dict = {}
    if ic_coil_src == "measured_pf":
        assert currents_df is not None
        t_cur = currents_df["time"].to_numpy(dtype=float)
        missing_cols = [c for c in order if c not in currents_df.columns]
        if missing_cols:
            raise RuntimeError(
                "ic_coil_currents=measured_pf but pf_currents.csv missing circuits: "
                + ", ".join(missing_cols)
            )
        for name in order:
            y = currents_df[name].to_numpy(dtype=float)
            ic_currents[name] = float(_interp_series(t_drive0, t_cur, y, name))
        print(
            f"[INFO] ic_coil_currents=measured_pf at t_drive0={t_drive0:.6f}: "
            + str({k: round(v, 3) for k, v in ic_currents.items()}),
            flush=True,
        )
    else:
        ic_currents = dict(dump.get("coil_currents") or {})
        print(
            f"[INFO] ic_coil_currents=inverse_dump ({len(ic_currents)} circuits)",
            flush=True,
        )
    _set_currents(tokamak, ic_currents)

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
    # Prefer measured Ip at t_drive0 when clamp/measured-IC path is active.
    if (clamp_ip or ic_coil_src == "measured_pf") and ip_df is not None and ip_col is not None:
        try:
            t_ip0 = ip_df["time"].to_numpy(dtype=float)
            y_ip0 = ip_df[ip_col].to_numpy(dtype=float)
            Ip0 = float(_interp_series(t_drive0, t_ip0, y_ip0, "Ip"))
            print(f"[INFO] Ip0 from measured ip.csv at t_drive0: {Ip0:.6g} A", flush=True)
        except Exception as _ipe0:
            print(f"[WARN] measured Ip0 interp failed, using inverse dump Ip: {_ipe0}", flush=True)
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

    # IC magnetic axis for axis-drift soft-stop (Alfvén-unstable / no passives).
    r_axis0 = float("nan")
    z_axis0 = float("nan")
    try:
        opt0 = stepping.eq1.opt[0]
        r_axis0, z_axis0 = float(opt0[0]), float(opt0[1])
    except Exception:
        try:
            opt0 = eq._profiles.opt[0]
            r_axis0, z_axis0 = float(opt0[0]), float(opt0[1])
        except Exception:
            pass
    if abort_axis_drift_m is not None and not (
        math.isfinite(r_axis0) and math.isfinite(z_axis0)
    ):
        print(
            "[WARN] abort_when_axis_drift_m set but IC axis unavailable — drift gate disabled",
            flush=True,
        )
        abort_axis_drift_m = None
    else:
        print(
            f"[INFO] IC magnetic axis R={r_axis0:.4f} Z={z_axis0:.4f} "
            f"(abort_when_axis_drift_m={abort_axis_drift_m})",
            flush=True,
        )

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
    early_stop = None
    early_stop_detail = None
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
        alpha_m_step = alpha_m0
        alpha_n_step = alpha_n0
        fvac_step = float(dump["fvac"])
        ip_clamp_t = None
        if use_trajectory:
            assert interpolate_profile_at is not None and traj is not None
            knobs = interpolate_profile_at(traj, t_abs)
            paxis_step = float(knobs["paxis"])
            alpha_m_step = float(knobs["alpha_m"])
            alpha_n_step = float(knobs["alpha_n"])
            fvac_step = float(knobs["fvac"])
            profiles_parameters = {
                "paxis": float(paxis_step),
                "alpha_m": float(alpha_m_step),
                "alpha_n": float(alpha_n_step),
            }
            # fvac is not in nlstepper profiles_parameters on all FreeGSNKE builds;
            # record it in history/meta. Shape alphas+paxis are the declared drive.
            _ = fvac_step
        elif scale_paxis:
            assert ip_df is not None and ip_col is not None
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

        # Declared replay law: pin Ip to measured before nlstepper.
        # FreeGSNKE linear_solve.stepper sets forcing[-1]=0 (no Ip voltage drive).
        if clamp_ip:
            assert ip_df is not None and ip_col is not None
            t_ip = ip_df["time"].to_numpy(dtype=float)
            y_ip = ip_df[ip_col].to_numpy(dtype=float)
            ip_clamp_t = float(_interp_series(t_abs, t_ip, y_ip, "Ip"))
            if not math.isfinite(ip_clamp_t):
                raise RuntimeError(f"clamp_ip_to_measured: non-finite Ip at t={t_abs}")
            norm = float(stepping.plasma_norm_factor)
            if not (abs(norm) > 0.0):
                raise RuntimeError("clamp_ip_to_measured: plasma_norm_factor is zero")
            stepping.currents_vec[-1] = ip_clamp_t / norm
            try:
                stepping.currents_vec_m1[-1] = ip_clamp_t / norm
            except Exception:
                pass
            stepping.profiles1.Ip = ip_clamp_t
            stepping.profiles2.Ip = ip_clamp_t
            if profiles_parameters is None:
                profiles_parameters = {}
            profiles_parameters["Ip"] = ip_clamp_t

        print(
            f"Step {step}/{n_steps - 1}  t_abs={t_abs:.6f}  linear_only={linear_only} "
            f"traj={use_trajectory} scale_paxis={scale_paxis} clamp_ip={clamp_ip} "
            f"paxis={paxis_step:.6g}"
            + (f" Ip_clamp={ip_clamp_t:.6g}" if ip_clamp_t is not None else ""),
            flush=True,
        )
        step_ok = True
        wd = _arm_step_watchdog(per_step_timeout_s, step)
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
            _write_history_csv(OUT / "history.csv", history, coil_names)
            break
        finally:
            try:
                wd.cancel()
            except Exception:
                pass

        # Re-pin Ip after the step so history / next IC match the declared law
        # (nlstepper can still drift Ip via mutuals when forcing[-1]=0).
        if clamp_ip and ip_clamp_t is not None and step_ok:
            norm = float(stepping.plasma_norm_factor)
            stepping.currents_vec[-1] = ip_clamp_t / norm
            stepping.profiles1.Ip = ip_clamp_t
            stepping.profiles2.Ip = ip_clamp_t

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
            if clamp_ip and ip_clamp_t is not None:
                Ip = float(ip_clamp_t)
            else:
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
                try:
                    from mast_freegsnke.equilibrium_presentation import (
                        plot_equilibrium_curated,
                    )

                    plot_equilibrium_curated(ax, stepping.eq1, tokamak)
                except Exception:
                    stepping.eq1.plot(axis=ax, show=False)
                    tokamak.plot(axis=ax, show=False)
                ax.set_title(f"evolutive step {step}  t={t_abs:.4f}s")
                fig.tight_layout()
                fig.savefig(OUT / f"eq_snapshot_step{step:04d}.png", dpi=120, bbox_inches="tight")
                plt.close(fig)
            except Exception as e:
                print(f"[WARN] snapshot failed at step {step}: {e}", flush=True)

        # Soft-stop before hung nlstepper: Ip collapsed vs measured (shot 30201 pattern).
        if (
            abort_ip_frac is not None
            and ip_df is not None
            and ip_col is not None
            and math.isfinite(Ip)
        ):
            try:
                t_ip = ip_df["time"].to_numpy(dtype=float)
                y_ip = ip_df[ip_col].to_numpy(dtype=float)
                ip_meas = float(_interp_series(t_abs, t_ip, y_ip, "Ip"))
            except Exception as _ipe:
                ip_meas = float("nan")
                print(f"[WARN] measured Ip interp failed: {_ipe}", flush=True)
            if math.isfinite(ip_meas) and abs(ip_meas) > 0.0:
                frac = abs(Ip) / abs(ip_meas)
                if frac < float(abort_ip_frac):
                    early_stop = "ip_below_measured_frac"
                    early_stop_detail = {
                        "t_abs": float(t_abs),
                        "step": int(step),
                        "Ip_evolutive": float(Ip),
                        "Ip_measured": float(ip_meas),
                        "frac": float(frac),
                        "threshold": float(abort_ip_frac),
                    }
                    print(
                        f"[ABORT] evolutive Ip collapsed vs measured: "
                        f"|Ip_evo|/|Ip_meas|={frac:.4f} < {abort_ip_frac} "
                        f"at step {step} t={t_abs:.6f} "
                        f"(Ip_evo={Ip:.4g} A, Ip_meas={ip_meas:.4g} A) — "
                        f"stopping before hung nlstepper; partial history retained",
                        flush=True,
                    )
                    break

        # Soft-stop: magnetic axis drifted too far (no-passive Alfvén instability).
        if (
            abort_axis_drift_m is not None
            and math.isfinite(Raxis)
            and math.isfinite(Zaxis)
            and math.isfinite(r_axis0)
            and math.isfinite(z_axis0)
        ):
            drift = math.hypot(Raxis - r_axis0, Zaxis - z_axis0)
            if drift > float(abort_axis_drift_m):
                early_stop = "axis_drift"
                early_stop_detail = {
                    "t_abs": float(t_abs),
                    "step": int(step),
                    "Raxis": float(Raxis),
                    "Zaxis": float(Zaxis),
                    "Raxis0": float(r_axis0),
                    "Zaxis0": float(z_axis0),
                    "drift_m": float(drift),
                    "threshold_m": float(abort_axis_drift_m),
                }
                print(
                    f"[ABORT] evolutive axis drift {drift:.4f} m > "
                    f"{abort_axis_drift_m} m at step {step} t={t_abs:.6f} "
                    f"(R,Z)=({Raxis:.4f},{Zaxis:.4f}) vs IC "
                    f"({r_axis0:.4f},{z_axis0:.4f}) — stopping before hung "
                    f"nlstepper (no passives / Alfvén-unstable); partial history retained",
                    flush=True,
                )
                break

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
        "clamp_ip_to_measured": clamp_ip,
        "ic_coil_currents": ic_coil_src,
        "plasma_resistivity_ohm_m": eta,
        "max_solving_iterations": max_iter,
        "per_step_timeout_s": per_step_timeout_s,
        "abort_when_ip_below_measured_frac": abort_ip_frac,
        "abort_when_axis_drift_m": abort_axis_drift_m,
        "early_stop": early_stop,
        "early_stop_detail": early_stop_detail,
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
        "profile_source": (
            "profile_trajectory_authority"
            if use_trajectory
            else "inverse_dump_IC"
        ),
        "profile_policy": {
            "alpha_m_alpha_n_fvac": (
                "from_profile_trajectory"
                if use_trajectory
                else "held_from_inverse_IC"
            ),
            "scale_paxis_with_ip": scale_paxis,
            "clamp_ip_to_measured": clamp_ip,
            "ic_coil_currents": ic_coil_src,
            "profile_trajectory": bool(use_trajectory),
            "profile_trajectory_fit_mode": (
                traj.fit_mode_used if use_trajectory else None
            ),
            "profile_trajectory_sha256": (
                traj.content_sha256() if use_trajectory else None
            ),
            "paxis0": paxis0,
            "Ip0": Ip0,
        },
        "limitations": [
            "FAIR-MAST Level-2 supplies measured voltages p1/p2/p4/p5 (primary drive)",
            "P6 (and any from_current_ohmic) uses V=I×R with FreeGSNKE coil_resist — not invented R",
            "MAST-U-only divertor circuits (D1–D7/Dp) use declared default_V=0 (no classic-MAST FAIR-MAST drive)",
            "Mismatch is FreeGSNKE structural coils vs classic MAST PF set — not missing FAIR-MAST voltages",
            (
                "Profile knobs from declared profile_trajectory (ADR-004); overrides scale_paxis_with_ip"
                if use_trajectory
                else (
                    "paxis scaled with measured Ip(t)/Ip(t0) (declared law)"
                    if scale_paxis
                    else "Profile parameters held from IC (scale_paxis_with_ip=false)"
                )
            ),
            (
                "IC coil currents from measured pf_currents.csv at t_drive0 "
                "(ic_coil_currents=measured_pf) so applied V≈IR"
                if ic_coil_src == "measured_pf"
                else "IC coil currents from inverse_dump (shape-optimised; may disagree with measured PF)"
            ),
            (
                "Ip clamped each step to FAIR-MAST ip.csv (clamp_ip_to_measured=true replay law; "
                "FreeGSNKE linear stepper has no Ip voltage drive)"
                if clamp_ip
                else "Ip free under circuit mutuals (clamp_ip_to_measured=false)"
            ),
            "Passives empty until configs/passive_resistivity.json has cited resistivity (Alfven-unstable risk)",
        ],
    }
    if early_stop:
        meta["limitations"].append(
            f"early_stop={early_stop}: evolutive Ip diverged from measured "
            f"(see early_stop_detail); remaining steps not run"
        )
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
