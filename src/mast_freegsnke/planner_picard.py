"""Path B3: GSPulse-style Picard outer loop — freeze plasma offsets from FreeGSNKE GS.

At each outer iteration:
  1. Forward Grad–Shafranov at planner knots with planned coil currents
     (ConstrainPaxisIp from profile_trajectory or execution_authority + measured Ip).
  2. Split total ψ/B into vacuum (G @ I) + plasma; set isoflux sensor targets to
     −plasma so the QP linear model is ``G @ I + plasma ≈ 0``.
  3. Re-solve the trajectory QP.

Never invents Ip, profiles, geometry, or coil limits. Soft-skips when FreeGSNKE /
authorities / GS solves are unavailable unless ``require_picard=true``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .planner import PlannerError
from .planner_isoflux import IsofluxSensors, _tokamak_from_machine


def load_ip_series(inputs_dir: Path) -> Tuple[np.ndarray, np.ndarray]:
    """Return (t_s, Ip_A) from inputs/ip.csv — fail if missing/non-finite."""
    path = Path(inputs_dir) / "ip.csv"
    if not path.is_file():
        raise PlannerError("Picard requires inputs/ip.csv (measured Ip) — never invent Ip")
    df = pd.read_csv(path)
    if "time" not in df.columns:
        raise PlannerError("ip.csv missing time column")
    col = None
    for c in ("Ip", "ip", "plasma_current", "I_p"):
        if c in df.columns:
            col = c
            break
    if col is None:
        nums = [c for c in df.columns if c != "time"]
        if len(nums) == 1:
            col = nums[0]
        else:
            raise PlannerError("ip.csv: cannot identify Ip column")
    t = np.asarray(df["time"], dtype=float)
    y = np.asarray(df[col], dtype=float)
    m = np.isfinite(t) & np.isfinite(y)
    t, y = t[m], y[m]
    if t.size < 2:
        raise PlannerError("ip.csv has insufficient finite samples for Picard")
    order = np.argsort(t)
    return t[order], y[order]


def interp_ip(t_s: float, t_src: np.ndarray, ip_src: np.ndarray) -> float:
    if float(t_s) < float(t_src[0]) - 1e-12 or float(t_s) > float(t_src[-1]) + 1e-12:
        raise PlannerError(
            f"Picard Ip query t={t_s} outside measured ip.csv [{t_src[0]}, {t_src[-1]}]"
        )
    return float(np.interp(float(t_s), t_src, ip_src))


def resolve_profile_knobs(
    *,
    inputs_dir: Path,
    t_s: float,
) -> Dict[str, Any]:
    """ConstrainPaxisIp knobs: prefer profile_trajectory, else execution_authority."""
    from .profile_trajectory import interpolate_profile_at, try_load_built_trajectory

    traj = try_load_built_trajectory(Path(inputs_dir))
    if traj is not None:
        knobs = interpolate_profile_at(traj, t_s)
        return {
            "paxis": float(knobs["paxis"]),
            "fvac": float(knobs["fvac"]),
            "alpha_m": float(knobs["alpha_m"]),
            "alpha_n": float(knobs["alpha_n"]),
            "source": "profile_trajectory",
        }

    ea_path = (
        Path(inputs_dir) / "execution_authority" / "execution_authority_bundle.json"
    )
    if not ea_path.is_file():
        raise PlannerError(
            "Picard needs profile_trajectory (status=ok) or "
            "inputs/execution_authority/execution_authority_bundle.json"
        )
    from .execution_authority import load_execution_authority_bundle

    bundle = load_execution_authority_bundle(ea_path)
    p = bundle.profile
    return {
        "paxis": float(p.paxis_Pa),
        "fvac": float(p.fvac),
        "alpha_m": float(p.alpha_m),
        "alpha_n": float(p.alpha_n),
        "source": "execution_authority_held",
    }


def load_grid_and_solver(inputs_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    ea_path = (
        Path(inputs_dir) / "execution_authority" / "execution_authority_bundle.json"
    )
    if not ea_path.is_file():
        raise PlannerError(
            "Picard requires execution_authority bundle for grid/solver tolerances"
        )
    from .execution_authority import load_execution_authority_bundle

    bundle = load_execution_authority_bundle(ea_path)
    g = bundle.grid
    grid = {
        "Rmin": float(g.Rmin),
        "Rmax": float(g.Rmax),
        "Zmin": float(g.Zmin),
        "Zmax": float(g.Zmax),
        "nx": int(g.nx),
        "ny": int(g.ny),
    }
    solv = {
        "forward_target_relative_tolerance": float(
            bundle.solver.forward_target_relative_tolerance
        ),
        "max_solving_iterations": int(bundle.solver.multitime.max_solving_iterations),
    }
    return grid, solv


def set_circuit_currents(tokamak: Any, currents: Dict[str, float]) -> None:
    from .tokamak_currents import set_tokamak_currents

    set_tokamak_currents(tokamak, currents)

def _psi_at_points(eq: Any, r: np.ndarray, z: np.ndarray) -> np.ndarray:
    r = np.asarray(r, dtype=float).ravel()
    z = np.asarray(z, dtype=float).ravel()
    if hasattr(eq, "psiRZ"):
        out = eq.psiRZ(r, z)
        return np.asarray(out, dtype=float).ravel()
    raise PlannerError("Equilibrium missing psiRZ for Picard plasma offsets")


def _B_at_points(eq: Any, r: np.ndarray, z: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    r = np.asarray(r, dtype=float).ravel()
    z = np.asarray(z, dtype=float).ravel()
    if hasattr(eq, "Br") and hasattr(eq, "Bz"):
        return (
            np.asarray(eq.Br(r, z), dtype=float).ravel(),
            np.asarray(eq.Bz(r, z), dtype=float).ravel(),
        )
    raise PlannerError("Equilibrium missing Br/Bz for Picard x-point offsets")


def apply_plasma_offsets_to_sensors(
    *,
    isoflux: Optional[IsofluxSensors],
    xpoint_B: Optional[IsofluxSensors],
    I_k: np.ndarray,
    psi_total: Optional[np.ndarray] = None,
    Br_total: Optional[np.ndarray] = None,
    Bz_total: Optional[np.ndarray] = None,
) -> Tuple[Optional[IsofluxSensors], Optional[IsofluxSensors]]:
    """Update targets so vacuum G @ I ≈ −plasma (Picard freeze)."""
    I_k = np.asarray(I_k, dtype=float).ravel()
    iso_out = isoflux
    xp_out = xpoint_B

    if isinstance(isoflux, IsofluxSensors) and isoflux.G_psi_full is not None:
        if psi_total is None or isoflux.ref_index is None:
            raise PlannerError("isoflux Picard needs psi_total and ref_index")
        G_full = np.asarray(isoflux.G_psi_full, dtype=float)
        psi_vac = G_full @ I_k
        psi_p = np.asarray(psi_total, dtype=float).ravel() - psi_vac
        ref_i = int(isoflux.ref_index)
        b_rel = np.delete(psi_p - psi_p[ref_i], ref_i)
        if b_rel.shape != isoflux.target.shape:
            raise PlannerError("isoflux plasma offset shape mismatch")
        iso_out = replace(
            isoflux,
            target=-b_rel,
            note=(isoflux.note or "") + "; plasma_picard_offset",
        )

    if isinstance(xpoint_B, IsofluxSensors) and xpoint_B.G_Br_full is not None:
        if Br_total is None or Bz_total is None:
            raise PlannerError("x-point Picard needs Br_total/Bz_total")
        G_Br = np.asarray(xpoint_B.G_Br_full, dtype=float)
        G_Bz = np.asarray(xpoint_B.G_Bz_full, dtype=float)
        Br_p = np.asarray(Br_total, dtype=float).ravel() - (G_Br @ I_k)
        Bz_p = np.asarray(Bz_total, dtype=float).ravel() - (G_Bz @ I_k)
        b = np.concatenate([Br_p, Bz_p])
        if b.shape != xpoint_B.target.shape:
            raise PlannerError("xpoint_B plasma offset shape mismatch")
        xp_out = replace(
            xpoint_B,
            target=-b,
            note=(xpoint_B.note or "") + "; plasma_picard_offset",
        )

    return iso_out, xp_out


def solve_forward_gs_at_currents(
    *,
    machine_dir: Path,
    circuit_order: Sequence[str],
    currents_A: Dict[str, float],
    Ip_A: float,
    profile_knobs: Dict[str, float],
    grid: Dict[str, Any],
    solver_spec: Dict[str, Any],
    tokamak: Any = None,
    eq: Any = None,
) -> Dict[str, Any]:
    """One forward GS solve; returns eq + status (does not invent currents/Ip/profiles)."""
    try:
        from freegsnke import equilibrium_update  # type: ignore
        from freegsnke.jtor_update import ConstrainPaxisIp  # type: ignore
        from freegsnke import GSstaticsolver  # type: ignore
    except Exception as e:
        raise PlannerError(
            f"freegsnke not importable for Picard GS: {type(e).__name__}: {e}"
        ) from e

    tok = tokamak if tokamak is not None else _tokamak_from_machine(Path(machine_dir))
    set_circuit_currents(tok, {str(k): float(v) for k, v in currents_A.items()})
    if eq is None:
        eq = equilibrium_update.Equilibrium(
            tokamak=tok,
            Rmin=float(grid["Rmin"]),
            Rmax=float(grid["Rmax"]),
            Zmin=float(grid["Zmin"]),
            Zmax=float(grid["Zmax"]),
            nx=int(grid["nx"]),
            ny=int(grid["ny"]),
        )
    else:
        eq.tokamak = tok
        eq.solved = False

    profiles = ConstrainPaxisIp(
        eq=eq,
        paxis=float(profile_knobs["paxis"]),
        Ip=float(Ip_A),
        fvac=float(profile_knobs["fvac"]),
        alpha_m=float(profile_knobs["alpha_m"]),
        alpha_n=float(profile_knobs["alpha_n"]),
    )
    solver = GSstaticsolver.NKGSsolver(eq)
    tol = float(solver_spec.get("forward_target_relative_tolerance", 1e-6))
    maxit = int(solver_spec.get("max_solving_iterations", 50))
    solver.solve(
        eq=eq,
        profiles=profiles,
        constrain=None,
        target_relative_tolerance=tol,
        max_solving_iterations=maxit,
        verbose=False,
    )
    rel = float(getattr(solver, "relative_change", float("nan")))
    return {
        "ok": True,
        "converged": bool(np.isfinite(rel) and rel <= tol),
        "rel_change": rel,
        "eq": eq,
        "tokamak": tok,
    }


def update_isoflux_pack_from_gs(
    pack: Dict[str, Any],
    *,
    knot_index: int,
    I_k: np.ndarray,
    eq: Any,
) -> Dict[str, Any]:
    """Mutate one knot's sensor targets from a solved equilibrium."""
    knots = list(pack.get("knots") or [])
    if knot_index < 0 or knot_index >= len(knots):
        return pack
    entry = dict(knots[knot_index])
    iso = entry.get("isoflux")
    xp = entry.get("xpoint_B")
    psi_tot = None
    Br_tot = None
    Bz_tot = None
    if isinstance(iso, IsofluxSensors) and iso.r_all_m is not None:
        psi_tot = _psi_at_points(eq, iso.r_all_m, iso.z_all_m)
    if isinstance(xp, IsofluxSensors) and xp.r_all_m is not None:
        Br_tot, Bz_tot = _B_at_points(eq, xp.r_all_m, xp.z_all_m)
    iso2, xp2 = apply_plasma_offsets_to_sensors(
        isoflux=iso if isinstance(iso, IsofluxSensors) else None,
        xpoint_B=xp if isinstance(xp, IsofluxSensors) else None,
        I_k=I_k,
        psi_total=psi_tot,
        Br_total=Br_tot,
        Bz_total=Bz_tot,
    )
    entry["isoflux"] = iso2
    entry["xpoint_B"] = xp2
    pb = entry.get("psi_bry")
    if isinstance(pb, IsofluxSensors) and pb.r_all_m is not None:
        from .planner_plasma_scalars import apply_plasma_offset_psi_bry

        if psi_tot is None:
            psi_tot = _psi_at_points(eq, pb.r_all_m, pb.z_all_m)
        entry["psi_bry"] = apply_plasma_offset_psi_bry(
            pb, I_k=I_k, psi_total=psi_tot
        )
    knots[knot_index] = entry
    out = dict(pack)
    out["knots"] = knots
    out["mode"] = "vacuum_coil_greens_plus_plasma_picard"
    out["note"] = (
        "Vacuum Green’s + frozen plasma offsets from FreeGSNKE forward GS (Path B3 Picard)"
    )
    return out


def run_picard_outer_loop(
    *,
    machine_dir: Path,
    inputs_dir: Path,
    circuit_order: Sequence[str],
    times: np.ndarray,
    I_plan: np.ndarray,
    isoflux_pack: Dict[str, Any],
    qp_kwargs: Dict[str, Any],
    max_picard_iterations: int = 2,
    picard_rel_tol: float = 1.0e-3,
    solve_gs_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    solve_qp_fn: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Picard outer loop. ``qp_kwargs`` are passed to ``solve_trajectory_qp``."""
    from .planner import solve_trajectory_qp

    if max_picard_iterations < 1:
        return {
            "ok": False,
            "status": "disabled",
            "picard": False,
            "converged": False,
            "picard_rel_tol": float(picard_rel_tol),
            "note": "max_picard_iterations < 1",
            "I": I_plan,
            "sol": None,
            "isoflux_pack": isoflux_pack,
            "history": [],
        }

    order = [str(c) for c in circuit_order]
    t_ip, ip_src = load_ip_series(Path(inputs_dir))
    grid, solv = load_grid_and_solver(Path(inputs_dir))
    times = np.asarray(times, dtype=float).ravel()
    I = np.asarray(I_plan, dtype=float).copy()
    pack = isoflux_pack
    n_t = I.shape[0]
    n_pack = len(pack.get("knots") or [])
    n_use = min(n_t, n_pack, times.size)
    if n_use < 1:
        return {
            "ok": False,
            "status": "skipped_no_knots",
            "picard": False,
            "converged": False,
            "picard_rel_tol": float(picard_rel_tol),
            "note": "no overlapping planner/isoflux knots",
            "I": I,
            "sol": None,
            "isoflux_pack": pack,
            "history": [],
        }

    gs_fn = solve_gs_fn or solve_forward_gs_at_currents
    qp_fn = solve_qp_fn or solve_trajectory_qp
    history: List[Dict[str, Any]] = []
    tok = None
    eq = None
    any_gs = False
    sol: Optional[Dict[str, Any]] = None
    converged = False
    n_outers_done = 0
    tol = float(picard_rel_tol)
    if not np.isfinite(tol) or tol <= 0.0:
        raise ValueError("picard_rel_tol must be finite and > 0")

    for outer in range(int(max_picard_iterations)):
        I_prev = I.copy()
        n_ok = 0
        n_fail = 0
        profile_src = None
        for k in range(n_use):
            t_k = float(times[k])
            try:
                Ip = interp_ip(t_k, t_ip, ip_src)
                knobs = resolve_profile_knobs(inputs_dir=Path(inputs_dir), t_s=t_k)
                profile_src = knobs.get("source")
                currents = {order[j]: float(I[k, j]) for j in range(len(order))}
                gs = gs_fn(
                    machine_dir=Path(machine_dir),
                    circuit_order=order,
                    currents_A=currents,
                    Ip_A=Ip,
                    profile_knobs=knobs,
                    grid=grid,
                    solver_spec=solv,
                    tokamak=tok,
                    eq=eq,
                )
                tok = gs.get("tokamak", tok)
                eq = gs.get("eq", eq)
                pack = update_isoflux_pack_from_gs(
                    pack, knot_index=k, I_k=I[k], eq=eq
                )
                n_ok += 1
                any_gs = True
            except Exception as e:
                n_fail += 1
                history.append(
                    {
                        "outer": outer,
                        "knot": k,
                        "status": "gs_failed",
                        "error": f"{type(e).__name__}: {e}",
                    }
                )

        if n_ok < 1:
            return {
                "ok": False,
                "status": "skipped_gs_failed",
                "picard": False,
                "converged": False,
                "picard_rel_tol": tol,
                "note": f"all GS solves failed on Picard outer={outer}",
                "I": I,
                "sol": None,
                "isoflux_pack": pack,
                "history": history,
            }

        qp_call = dict(qp_kwargs)
        qp_call["isoflux_pack"] = pack
        sol = qp_fn(**qp_call)
        I = np.asarray(sol["I"], dtype=float)
        n_outers_done = outer + 1
        denom = float(np.linalg.norm(I_prev.ravel()))
        if denom <= 0.0:
            rel = float(np.linalg.norm((I - I_prev).ravel()))
        else:
            rel = float(np.linalg.norm((I - I_prev).ravel()) / denom)
        converged = bool(np.isfinite(rel) and rel <= tol)
        history.append(
            {
                "outer": outer,
                "n_gs_ok": n_ok,
                "n_gs_fail": n_fail,
                "profile_source": profile_src,
                "n_voltage_violations_raw": sol.get("n_voltage_violations_raw"),
                "cost_final": (sol.get("cost_history") or [None])[-1],
                "I_rel_change": rel,
                "converged": converged,
            }
        )
        if converged:
            break

    return {
        "ok": bool(any_gs),
        "status": "ok" if any_gs else "skipped",
        "picard": bool(any_gs),
        "converged": bool(converged and any_gs),
        "picard_rel_tol": tol,
        "picard_mode": "forward_gs_freeze_plasma_offsets",
        "n_outers": int(n_outers_done),
        "n_outers_max": int(max_picard_iterations),
        "note": (
            "Picard: FreeGSNKE forward GS → freeze plasma ψ/B offsets → re-QP "
            "(not upstream GSPulse MATLAB/MEQ)"
            + (
                f"; converged I_rel<={tol:g} after {n_outers_done} outer(s)"
                if converged
                else f"; not converged to I_rel<={tol:g} after {n_outers_done} outer(s)"
            )
        ),
        "I": I,
        "sol": sol,
        "isoflux_pack": pack,
        "history": history,
    }

