"""Science-facing audit pack for a completed SHOT/<N> run (v11.7.0).

Uses only measured FAIR-MAST traces + declared FreeGSNKE outputs.
Never invents resistivity, calibration factors, voltages, or equilibria.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


def _safe_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _interp(t_src: np.ndarray, y_src: np.ndarray, t_q: np.ndarray) -> np.ndarray:
    order = np.argsort(t_src)
    return np.interp(t_q, t_src[order], y_src[order])


def score_evolutive_ip(run_dir: Path) -> Dict[str, Any]:
    """Compare evolutive history Ip(t) to measured inputs/ip.csv (interpolated).

    Fail-closed soft: missing files → ok=False with reason (not a fabricated score).
    When clamp_ip_to_measured is true (meta), status is clamp_tautology — near-zero
    residual is expected by construction, not circuit validation.
    """
    run_dir = Path(run_dir)
    report: Dict[str, Any] = {
        "ok": False,
        "n": 0,
        "rms_A": None,
        "mae_A": None,
        "max_abs_A": None,
        "rms_rel": None,
        "status": None,
        "clamp_ip_to_measured": None,
        "errors": [],
    }
    from .shot_layout import evolutive_dir, resolve_run_path

    evo_meta = None
    for cand in (
        run_dir / "03_reconstruction" / "evolutive" / "evolutive_meta.json",
        run_dir / "evolutive" / "evolutive_meta.json",
    ):
        evo_meta = _safe_json(cand)
        if isinstance(evo_meta, dict):
            break
    clamp_ip = None
    if isinstance(evo_meta, dict) and "clamp_ip_to_measured" in evo_meta:
        clamp_ip = bool(evo_meta.get("clamp_ip_to_measured"))
    report["clamp_ip_to_measured"] = clamp_ip

    hist = resolve_run_path(
        run_dir, "evolutive/history.csv", "03_reconstruction/evolutive/history.csv"
    )
    ip_path = run_dir / "inputs" / "ip.csv"
    if hist is None or not hist.exists():
        report["errors"].append("missing_evolutive_history_csv")
        return report
    if not ip_path.exists():
        report["errors"].append("missing_inputs_ip_csv")
        return report
    try:
        hdf = pd.read_csv(hist)
        idf = pd.read_csv(ip_path)
    except Exception as e:
        report["errors"].append(f"csv_read_failed:{type(e).__name__}:{e}")
        return report
    if "t_abs" not in hdf.columns or "Ip" not in hdf.columns:
        report["errors"].append("history_missing_t_abs_or_Ip")
        return report
    if "time" not in idf.columns or "ip" not in idf.columns:
        report["errors"].append("ip_csv_missing_time_or_ip")
        return report
    t_h = hdf["t_abs"].to_numpy(dtype=float)
    ip_h = hdf["Ip"].to_numpy(dtype=float)
    mask = np.isfinite(t_h) & np.isfinite(ip_h)
    if hasattr(hdf, "columns") and "step_ok" in hdf.columns:
        ok_col = hdf["step_ok"].to_numpy()
        mask = mask & np.asarray([bool(x) for x in ok_col])
    t_h, ip_h = t_h[mask], ip_h[mask]
    if t_h.size < 2:
        report["errors"].append("fewer_than_2_valid_evolutive_Ip_samples")
        return report
    t_m = idf["time"].to_numpy(dtype=float)
    ip_m = idf["ip"].to_numpy(dtype=float)
    mfin = np.isfinite(t_m) & np.isfinite(ip_m)
    t_m, ip_m = t_m[mfin], ip_m[mfin]
    if t_m.size < 2:
        report["errors"].append("fewer_than_2_valid_measured_Ip_samples")
        return report
    ip_meas = _interp(t_m, ip_m, t_h)
    resid = ip_h - ip_meas
    rms = float(np.sqrt(np.mean(resid**2)))
    mae = float(np.mean(np.abs(resid)))
    max_abs = float(np.max(np.abs(resid)))
    scale = float(np.mean(np.abs(ip_meas)))
    rms_rel = float(rms / scale) if scale > 0.0 else None
    evo_root = evolutive_dir(run_dir)
    evo_root.mkdir(parents=True, exist_ok=True)
    out_csv = evo_root / "ip_residual.csv"
    pd.DataFrame(
        {
            "t_abs": t_h,
            "Ip_evolutive": ip_h,
            "Ip_measured": ip_meas,
            "residual_A": resid,
        }
    ).to_csv(out_csv, index=False)
    try:
        residual_rel = str(out_csv.resolve().relative_to(Path(run_dir).resolve())).replace("\\", "/")
    except Exception:
        residual_rel = "evolutive/ip_residual.csv"
    status = "ok"
    note = (
        "Ip_measured is FAIR-MAST Level-2 ip.csv interpolated to evolutive t_abs; "
        "not an invented metrology channel."
    )
    if clamp_ip is True:
        status = "clamp_tautology"
        note = (
            "clamp_ip_to_measured=true: Ip is pinned to ip.csv each step — residual "
            "near zero is expected by construction (not circuit / voltage validation). "
            "Prefer evolutive_raxis_drift / early_stop for soft physics honesty."
        )
    report.update(
        {
            "ok": True,
            "n": int(t_h.size),
            "rms_A": rms,
            "mae_A": mae,
            "max_abs_A": max_abs,
            "rms_rel": rms_rel,
            "residual_csv": residual_rel,
            "status": status,
            "note": note,
        }
    )
    if isinstance(evo_meta, dict):
        report["early_stop"] = evo_meta.get("early_stop")
        report["n_steps_recorded"] = evo_meta.get("n_steps_recorded")
        report["n_steps_requested"] = evo_meta.get("n_steps_requested")
        report["ic_coil_currents"] = evo_meta.get("ic_coil_currents")
        report["n_passive"] = evo_meta.get("n_passive")
    return report


def score_evolutive_raxis_drift(run_dir: Path) -> Dict[str, Any]:
    """Magnetic-axis drift vs IC from evolutive history / early_stop_detail.

    Honest soft metric when clamp_ip makes Ip residual a tautology. Never invents
    passives or ρ — reports observed drift only.
    """
    run_dir = Path(run_dir)
    report: Dict[str, Any] = {
        "ok": False,
        "n": 0,
        "Raxis0_m": None,
        "Zaxis0_m": None,
        "max_drift_m": None,
        "final_drift_m": None,
        "early_stop": None,
        "early_stop_drift_m": None,
        "threshold_m": None,
        "status": None,
        "errors": [],
    }
    from .shot_layout import evolutive_dir, resolve_run_path

    evo_meta = None
    for cand in (
        run_dir / "03_reconstruction" / "evolutive" / "evolutive_meta.json",
        run_dir / "evolutive" / "evolutive_meta.json",
    ):
        evo_meta = _safe_json(cand)
        if isinstance(evo_meta, dict):
            break
    if isinstance(evo_meta, dict):
        report["early_stop"] = evo_meta.get("early_stop")
        report["n_steps_recorded"] = evo_meta.get("n_steps_recorded")
        report["n_steps_requested"] = evo_meta.get("n_steps_requested")
        report["n_passive"] = evo_meta.get("n_passive")
        thr = evo_meta.get("abort_when_axis_drift_m")
        if thr is not None:
            try:
                report["threshold_m"] = float(thr)
            except (TypeError, ValueError):
                pass
        detail = evo_meta.get("early_stop_detail")
        if isinstance(detail, dict) and detail.get("drift_m") is not None:
            try:
                report["early_stop_drift_m"] = float(detail["drift_m"])
            except (TypeError, ValueError):
                pass
            if detail.get("Raxis0") is not None:
                try:
                    report["Raxis0_m"] = float(detail["Raxis0"])
                    report["Zaxis0_m"] = float(detail["Zaxis0"])
                except (TypeError, ValueError):
                    pass

    hist = resolve_run_path(
        run_dir, "evolutive/history.csv", "03_reconstruction/evolutive/history.csv"
    )
    if hist is None or not hist.exists():
        report["errors"].append("missing_evolutive_history_csv")
        return report
    try:
        hdf = pd.read_csv(hist)
    except Exception as e:
        report["errors"].append(f"csv_read_failed:{type(e).__name__}:{e}")
        return report
    if "Raxis" not in hdf.columns or "Zaxis" not in hdf.columns:
        report["errors"].append("history_missing_Raxis_or_Zaxis")
        return report
    r = hdf["Raxis"].to_numpy(dtype=float)
    z = hdf["Zaxis"].to_numpy(dtype=float)
    mask = np.isfinite(r) & np.isfinite(z)
    if "step_ok" in hdf.columns:
        mask = mask & np.asarray([bool(x) for x in hdf["step_ok"].to_numpy()])
    r, z = r[mask], z[mask]
    if r.size < 1:
        report["errors"].append("no_valid_axis_samples")
        return report
    r0 = float(report["Raxis0_m"]) if report["Raxis0_m"] is not None else float(r[0])
    z0 = float(report["Zaxis0_m"]) if report["Zaxis0_m"] is not None else float(z[0])
    drift = np.hypot(r - r0, z - z0)
    max_drift = float(np.max(drift))
    final_drift = float(drift[-1])
    evo_root = evolutive_dir(run_dir)
    evo_root.mkdir(parents=True, exist_ok=True)
    t_col = hdf["t_abs"].to_numpy(dtype=float)[mask] if "t_abs" in hdf.columns else np.arange(r.size)
    out_csv = evo_root / "raxis_drift.csv"
    pd.DataFrame(
        {
            "t_abs": t_col,
            "Raxis": r,
            "Zaxis": z,
            "drift_from_ic_m": drift,
        }
    ).to_csv(out_csv, index=False)
    try:
        residual_rel = str(out_csv.resolve().relative_to(Path(run_dir).resolve())).replace("\\", "/")
    except Exception:
        residual_rel = "evolutive/raxis_drift.csv"
    status = "ok"
    if report.get("early_stop") == "axis_drift":
        status = "early_stop_axis_drift"
    elif report.get("threshold_m") is not None and max_drift > float(report["threshold_m"]):
        status = "exceeded_threshold"
    report.update(
        {
            "ok": True,
            "n": int(r.size),
            "Raxis0_m": r0,
            "Zaxis0_m": z0,
            "max_drift_m": max_drift,
            "final_drift_m": final_drift,
            "status": status,
            "drift_csv": residual_rel,
            "note": (
                "Drift from IC magnetic axis (history R/Z vs first finite sample or "
                "early_stop_detail). Preferred soft metric when clamp_ip_to_measured "
                "makes Ip residual a tautology. n_passive=0 soft-stop is honesty."
            ),
        }
    )
    return report


def reconstruct_quality(run_dir: Path) -> Dict[str, Any]:
    """Summarize multi-time inverse solve modes (science gate for mixed fallback)."""
    st = _safe_json(Path(run_dir) / "synthetic" / "synthetic_times.json")
    out: Dict[str, Any] = {
        "available": st is not None,
        "overall_solve_mode": None,
        "n_inverse_converged": None,
        "n_forward_gs_fallback": None,
        "n_skipped": None,
        "n_times": None,
        "science_tier_hint": "unknown",
        "note": "Prefer scoring reconstruction quality only on converged inverse times.",
    }
    if st is None:
        return out
    overall = st.get("solve_mode")
    n_inv = int(st.get("n_inverse_converged") or 0)
    n_fwd = int(st.get("n_forward_gs_fallback") or 0)
    n_skip = int(st.get("n_skipped") or 0)
    n_times = int(st.get("n_times") or len(st.get("times") or []) or 0)
    out.update(
        {
            "overall_solve_mode": overall,
            "n_inverse_converged": n_inv,
            "n_forward_gs_fallback": n_fwd,
            "n_skipped": n_skip,
            "n_times": n_times,
            "per_time": st.get("per_time"),
        }
    )
    if overall == "full_inverse" and n_fwd == 0 and n_skip == 0:
        out["science_tier_hint"] = "green"
    elif n_inv > 0 and (n_fwd > 0 or n_skip > 0):
        out["science_tier_hint"] = "yellow_mixed_or_partial"
    elif n_inv == 0 and n_fwd > 0:
        out["science_tier_hint"] = "yellow_forward_gs_only"
    else:
        out["science_tier_hint"] = "red_no_solved_times"
    return out


def inverse_shape_gate_summary(run_dir: Path) -> Dict[str, Any]:
    """Surface GS stop vs declared shape acceptance (never equate the two).

    FreeGSNKE Inverse stops on GS residual / relative ψ update; shape_audit is
    our post-solve declared gate (execution_authority.inverse_shape_acceptance).
    """
    run_dir = Path(run_dir)
    out: Dict[str, Any] = {
        "available": False,
        "t0": None,
        "n_shape_accepted": 0,
        "n_gs_ok_shape_unverified": 0,
        "n_dn_missing_xpoints": 0,
        "n_with_audit": 0,
        "per_time_statuses": [],
        "note": (
            "FreeGSNKE stop = GS residual / relative tokamak-flux update; "
            "shape gate = declared solver.inverse_shape_acceptance (not a FreeGSNKE stop)."
        ),
    }
    # t0 dump result (if present)
    for cand in (
        run_dir / "03_reconstruction" / "inverse" / "inverse_result.json",
        run_dir / "inverse_result.json",
        run_dir / "03_reconstruction" / "inverse" / "full_inverse_result.json",
    ):
        obj = _safe_json(cand)
        if isinstance(obj, dict) and (
            obj.get("shape_audit") is not None or obj.get("shape_status") is not None
        ):
            aud = obj.get("shape_audit") if isinstance(obj.get("shape_audit"), dict) else {}
            try:
                rel = str(cand.resolve().relative_to(run_dir.resolve())).replace("\\", "/")
            except Exception:
                rel = str(cand)
            out["t0"] = {
                "path": rel,
                "status": obj.get("status"),
                "shape_accepted": obj.get("shape_accepted", aud.get("shape_accepted")),
                "shape_status": aud.get("shape_status") or obj.get("shape_status"),
                "constrain_loss_final": aud.get("constrain_loss_final")
                if aud
                else obj.get("constrain_loss_final"),
                "rel_change": obj.get("rel_change"),
                "fail_reasons": list(aud.get("fail_reasons") or []),
            }
            out["available"] = True
            break

    # Fallback: inverse_dump.pkl may hold shape_audit before JSON provenance existed.
    if out["t0"] is None:
        for cand in (
            run_dir / "inverse_dump.pkl",
            run_dir / "03_reconstruction" / "inverse" / "inverse_dump.pkl",
        ):
            if not cand.is_file():
                continue
            try:
                import pickle

                dump = pickle.loads(cand.read_bytes())
            except Exception:
                continue
            if not isinstance(dump, dict):
                continue
            aud = dump.get("shape_audit") if isinstance(dump.get("shape_audit"), dict) else {}
            if not aud and dump.get("t0_solve_status") is None:
                continue
            try:
                rel = str(cand.resolve().relative_to(run_dir.resolve())).replace("\\", "/")
            except Exception:
                rel = str(cand)
            out["t0"] = {
                "path": rel,
                "status": dump.get("t0_solve_status") or aud.get("shape_status"),
                "shape_accepted": aud.get("shape_accepted"),
                "shape_status": aud.get("shape_status"),
                "constrain_loss_final": aud.get("constrain_loss_final")
                if aud
                else dump.get("t0_constrain_loss_final"),
                "rel_change": dump.get("t0_rel_change"),
                "fail_reasons": list(aud.get("fail_reasons") or []),
            }
            out["available"] = True
            break

    st = _safe_json(run_dir / "synthetic" / "synthetic_times.json")
    if not isinstance(st, dict):
        return out
    statuses: List[str] = []
    n_acc = n_unv = n_dn = n_aud = 0
    for entry in st.get("per_time") or []:
        if not isinstance(entry, dict):
            continue
        aud = entry.get("shape_audit") if isinstance(entry.get("shape_audit"), dict) else {}
        status = str(
            aud.get("shape_status")
            or entry.get("status")
            or ""
        )
        if aud or entry.get("shape_accepted") is not None:
            n_aud += 1
            out["available"] = True
        if status in {"shape_accepted", "shape_plausible"} or entry.get("shape_accepted") is True:
            n_acc += 1
        elif status == "dn_missing_xpoints":
            n_dn += 1
        elif status in {"gs_converged_shape_unverified", "critical_unavailable"}:
            n_unv += 1
        if status:
            statuses.append(status)
    # Count t0 dump audit when multitime has no per-time shape_audit yet.
    if n_aud == 0 and isinstance(out.get("t0"), dict) and out["t0"].get("shape_status"):
        n_aud = 1
        st0 = str(out["t0"].get("shape_status") or "")
        if st0 in {"shape_accepted", "shape_plausible"}:
            n_acc = 1
        elif st0 == "dn_missing_xpoints":
            n_dn = 1
        elif st0 in {"gs_converged_shape_unverified", "critical_unavailable"}:
            n_unv = 1
        statuses = [st0]
    out.update(
        {
            "n_shape_accepted": n_acc,
            "n_gs_ok_shape_unverified": n_unv,
            "n_dn_missing_xpoints": n_dn,
            "n_with_audit": n_aud,
            "per_time_statuses": statuses,
            "overall_solve_mode": st.get("solve_mode"),
        }
    )
    return out


def ohmic_drive_inventory(run_dir: Path) -> Dict[str, Any]:
    """List circuits driven by from_current_ohmic (declared, not measured V)."""
    run_dir = Path(run_dir)
    vmap = None
    used = None
    for p in (
        run_dir / "contracts" / "voltage_map.resolved.json",
        run_dir / "inputs" / "voltage_map" / "voltage_map.json",
    ):
        vmap = _safe_json(p)
        if vmap:
            used = str(p)
            break
    apply = _safe_json(run_dir / "inputs" / "voltage_map_apply_report.json")
    ohmic: List[str] = []
    measured: List[str] = []
    zero_default: List[str] = []
    circuits = (vmap or {}).get("circuits") or {}
    if isinstance(circuits, dict):
        for name, spec in circuits.items():
            if not isinstance(spec, dict):
                continue
            combine = str(spec.get("combine") or "")
            if combine == "from_current_ohmic":
                ohmic.append(str(name))
            elif combine in {"identity", "sum", "mean"}:
                measured.append(str(name))
            elif combine == "default":
                zero_default.append(str(name))
    # Also accept apply-report ohmic list if map missing
    if not ohmic and isinstance(apply, dict):
        for name in apply.get("ohmic_circuits") or []:
            ohmic.append(str(name))
    resist = _safe_json(run_dir / "evolutive" / "coil_resist_snapshot.json")
    return {
        "source": used,
        "ohmic_circuits": sorted(set(ohmic)),
        "measured_voltage_circuits": sorted(set(measured)),
        "declared_zero_V_circuits": sorted(set(zero_default)),
        "coil_resist_snapshot_present": resist is not None,
        "apply_report_present": apply is not None,
        "uncertainty_note": (
            "P3/P6 (and any from_current_ohmic) use V=I×R with FreeGSNKE coil_resist "
            "(declared copper default unless authority overrides). This is not measured "
            "power-supply voltage; treat vertical-control / shape residuals with that "
            "uncertainty. Do not invent alternate V channels."
        ),
    }


def phase_timeline_from_window(run_dir: Path, *, pre: float = 0.02, post: float = 0.02) -> Dict[str, Any]:
    """Declared three-phase narrative from finalized formed-plasma window endpoints."""
    from .robustness.phase_segmentation import segment_phases_from_window
    from .robustness.schema import WindowDef

    w = _safe_json(Path(run_dir) / "inputs" / "window.json")
    if not w or w.get("t_start") is None or w.get("t_end") is None:
        return {"available": False, "errors": ["missing_or_invalid_inputs_window_json"]}
    win = WindowDef(window_id="formed_plasma", t_start=float(w["t_start"]), t_end=float(w["t_end"]))
    phases = segment_phases_from_window(win, pre=pre, post=post)
    phases["available"] = True
    phases["formed_plasma_window"] = {"t_start": win.t_start, "t_end": win.t_end}
    phases["note"] = (
        "Phases are window-derived (ramp_up/flat_top/ramp_down around formed-plasma "
        "t_start..t_end). Not ML phase detection; flat_top is the scored reconstruction window."
    )
    return phases


def passive_resistivity_status(run_dir: Path, repo_cfg_path: Optional[Path] = None) -> Dict[str, Any]:
    """Report passive resistivity authority status (awaiting vs populated)."""
    candidates = [
        Path(run_dir) / "inputs" / "passive_resistivity.json",
        Path(run_dir) / "contracts" / "passive_resistivity.json",
    ]
    if repo_cfg_path is not None:
        candidates.append(Path(repo_cfg_path))
    obj = None
    used = None
    for p in candidates:
        obj = _safe_json(p)
        if obj:
            used = str(p)
            break
    if obj is None:
        # Fall back to shipped config relative to package is not required
        return {
            "status": "unknown",
            "n_components": 0,
            "note": "passive_resistivity authority not snapshotted in this run; machine passives stay empty until cited ρ exists.",
        }
    comps = obj.get("components") or {}
    n = len(comps) if isinstance(comps, dict) else 0
    return {
        "status": obj.get("status") or ("populated" if n else "awaiting_authority"),
        "n_components": n,
        "path": used,
        "note": obj.get("notes")
        or "Populate components only with cited resistivity_ohm_m — never invent.",
    }


def forward_gate_summary(run_dir: Path) -> Dict[str, Any]:
    """Surface static Forward presentation provenance (not Inverse shape gate).

    Dump-current t0 vs measured-PF window; profile_source rollup from
    presentation/forward_times.json. Never equate Forward plots with Inverse DN.
    """
    run_dir = Path(run_dir)
    out: Dict[str, Any] = {
        "available": False,
        "n_ok": None,
        "n_converged": None,
        "n_completed_max_iter": None,
        "n_timeout": None,
        "n_error": None,
        "n_skipped": None,
        "n_times": None,
        "ic_psi_used": None,
        "window_currents": None,
        "profile_source_requested": None,
        "profile_sources_used": [],
        "forward_png_present": (run_dir / "forward_equilibrium.png").is_file(),
        "note": (
            "Static Forward: t0 GS on Inverse dump currents (optional dump ψ IC); "
            "window = solver.forward_window_currents (default measured_pf). Default "
            "profile_trajectory_if_ok when cited trajectory exists. Plots must use live "
            "Forward LCFS (not Inverse dump LCFS). n_converged = tol-met only; "
            "measured-PF Forward is not Inverse shape acceptance."
        ),
    }
    ft = None
    for cand in (
        run_dir / "presentation" / "forward_times.json",
        run_dir / "03_reconstruction" / "presentation" / "forward_times.json",
    ):
        ft = _safe_json(cand)
        if isinstance(ft, dict):
            try:
                out["path"] = str(cand.resolve().relative_to(run_dir.resolve())).replace("\\", "/")
            except Exception:
                out["path"] = str(cand)
            break
    if not isinstance(ft, dict):
        return out
    n_ok = int(ft.get("n_ok") or 0)
    n_skip = int(ft.get("n_skipped") or 0)
    n_times = int(ft.get("n_times") or len(ft.get("times") or []) or len(ft.get("per_time") or []) or 0)
    n_conv = ft.get("n_converged")
    if n_conv is None:
        n_conv = sum(
            1
            for e in (ft.get("per_time") or [])
            if isinstance(e, dict) and str(e.get("status") or "") == "converged"
        )
    n_maxit = ft.get("n_completed_max_iter")
    if n_maxit is None:
        n_maxit = sum(
            1
            for e in (ft.get("per_time") or [])
            if isinstance(e, dict) and str(e.get("status") or "") == "completed_max_iter"
        )
    srcs = ft.get("profile_sources_used")
    if not isinstance(srcs, list):
        srcs = []
        for e in ft.get("per_time") or []:
            if isinstance(e, dict) and e.get("profile_source_used"):
                srcs.append(str(e["profile_source_used"]))
        srcs = sorted(set(srcs))
    out.update(
        {
            "available": True,
            "n_ok": n_ok,
            "n_converged": int(n_conv),
            "n_completed_max_iter": int(n_maxit),
            "n_timeout": ft.get("n_timeout"),
            "n_error": ft.get("n_error"),
            "n_skipped": n_skip,
            "n_times": n_times,
            "solve_mode": ft.get("solve_mode"),
            "ic_psi_used": ft.get("ic_psi_used"),
            "window_currents": ft.get("window_currents") or "measured_pf",
            "profile_source_requested": ft.get("profile_source_requested"),
            "profile_sources_used": list(srcs),
            "forward_note": ft.get("note"),
        }
    )
    return out


def profile_trajectory_audit(run_dir: Path) -> Dict[str, Any]:
    """Surface ADR-004 trajectory fit mode (cited EFIT p′/ff′ vs scalar bridge)."""
    run_dir = Path(run_dir)
    out: Dict[str, Any] = {
        "available": False,
        "status": None,
        "fit_mode_used": None,
        "alphas_from_pprime": False,
        "n_knots": 0,
        "note": (
            "Richer α only when FAIR-MAST equilibrium supplies pprime (archive_profiles); "
            "scalar_bridge holds authority α and scales paxis∝wmhd — never invent α."
        ),
    }
    traj = None
    for cand in (
        run_dir / "inputs" / "profile_trajectory_authority" / "profile_trajectory.json",
        run_dir / "06_authorities" / "profile_trajectory_authority" / "profile_trajectory.json",
    ):
        traj = _safe_json(cand)
        if isinstance(traj, dict):
            try:
                out["path"] = str(cand.resolve().relative_to(run_dir.resolve())).replace(
                    "\\", "/"
                )
            except Exception:
                out["path"] = str(cand)
            break
    if not isinstance(traj, dict):
        return out
    prov = traj.get("provenance") if isinstance(traj.get("provenance"), dict) else {}
    mode = str(traj.get("fit_mode_used") or prov.get("fit_mode_used") or "")
    knots = traj.get("knots") if isinstance(traj.get("knots"), list) else []
    alphas_from_pp = mode == "archive_profiles" and bool(knots)
    if not alphas_from_pp and knots:
        # Inspect residual provenance on first knot
        k0 = knots[0] if isinstance(knots[0], dict) else {}
        res = k0.get("residual") if isinstance(k0.get("residual"), dict) else {}
        if res.get("alphas_source") == "efit_pprime_fit" or "pprime_rms_norm" in res:
            alphas_from_pp = True
    out.update(
        {
            "available": True,
            "status": traj.get("status"),
            "fit_mode_used": mode or None,
            "alphas_from_pprime": bool(alphas_from_pp),
            "n_knots": len(knots),
            "pprime_var": prov.get("pprime_var"),
            "ffprime_var": prov.get("ffprime_var"),
        }
    )
    if mode == "scalar_bridge":
        out["note"] = (
            "scalar_bridge: paxis∝wmhd with authority α held fixed — archive lacked usable "
            "pprime for α fit (not invented)."
        )
    elif alphas_from_pp:
        out["note"] = (
            "archive_profiles: α_m/α_n fitted to cited EFIT++ pprime; fvac held from "
            "execution_authority (ffprime residual recorded, not used to invent fvac)."
        )
    return out


def presentation_advisories(run_dir: Path) -> Dict[str, Any]:
    """Loud but non-blocking advisories when GIFs ≠ Inverse/EFIT DN is expected.

    Advisory only — never hard-fails a shot that has equilibrium data.
    """
    run_dir = Path(run_dir)
    items: List[str] = []
    expect_mismatch = False
    shape_gate = inverse_shape_gate_summary(run_dir)
    n_unv = int(shape_gate.get("n_gs_ok_shape_unverified") or 0)
    t0 = shape_gate.get("t0") or {}
    t0_st = str(t0.get("status") or t0.get("shape_status") or "")
    if n_unv > 0 or "shape_unverified" in t0_st:
        expect_mismatch = True
        items.append(
            "Inverse shape_unverified (or DN X/O not accepted): expect Forward measured-PF "
            "and Evolutive GIFs ≠ Inverse DN / archive DN — physics mismatch, not missing data."
        )
    fwd = forward_gate_summary(run_dir)
    win_curr = str(fwd.get("window_currents") or "measured_pf")
    if fwd.get("available"):
        if win_curr == "inverse_dump_currents":
            items.append(
                "Forward window_currents=inverse_dump_currents (SHAPE DEMO) — not science "
                "measured-PF; frames may look closer to Inverse but are not a matched archive drive."
            )
        else:
            expect_mismatch = True
            items.append(
                "Static Forward window = measured PF/Ip replay (not Inverse-optimized currents); "
                "expect GIFs ≠ Inverse DN / archive DN."
            )
    # High LCFS residual vs EFIT++ archive (advisory threshold declared here).
    lcfs_m: Optional[float] = None
    for cand in (
        run_dir / "04_efit_compare" / "shape_scorecard.json",
        run_dir / "shape_scorecard.json",
    ):
        sc = _safe_json(cand)
        if not isinstance(sc, dict):
            continue
        dist = sc.get("lcfs_distance") or {}
        if isinstance(dist, dict) and dist.get("mean_nn_symmetric_m") is not None:
            try:
                lcfs_m = float(dist["mean_nn_symmetric_m"])
            except (TypeError, ValueError):
                lcfs_m = None
            break
        for row in sc.get("rows") or []:
            if isinstance(row, dict) and row.get("metric") == "lcfs_mean_nn_symmetric":
                try:
                    lcfs_m = float(row.get("freegsnke"))
                except (TypeError, ValueError):
                    lcfs_m = None
                break
        if lcfs_m is not None:
            break
    high_lcfs = False
    if lcfs_m is not None and lcfs_m >= 0.05:
        high_lcfs = True
        expect_mismatch = True
        items.append(
            f"EFIT++ LCFS mean nearest-neighbour residual ≈ {lcfs_m:.3f} m (≥0.05 m): "
            "Forward/Evolutive frames will not match archive DN; see 04_efit_compare/."
        )
    traj = profile_trajectory_audit(run_dir)
    if traj.get("available") and traj.get("fit_mode_used") == "scalar_bridge":
        items.append(
            "profile_trajectory used scalar_bridge (α held from authority; paxis∝wmhd) — "
            "not a full EFIT p′ shape match."
        )
    evo_meta = None
    for cand in (
        run_dir / "03_reconstruction" / "evolutive" / "evolutive_meta.json",
        run_dir / "evolutive" / "evolutive_meta.json",
    ):
        evo_meta = _safe_json(cand)
        if isinstance(evo_meta, dict):
            break
    if isinstance(evo_meta, dict) and evo_meta.get("early_stop"):
        es = str(evo_meta.get("early_stop"))
        expect_mismatch = True
        n_rec = evo_meta.get("n_steps_recorded")
        n_req = evo_meta.get("n_steps_requested")
        steps_bit = ""
        if n_rec is not None and n_req is not None:
            steps_bit = f" ({n_rec}/{n_req} steps)"
        if es == "axis_drift":
            items.append(
                f"Evolutive early_stop=axis_drift{steps_bit} (n_passive=0 soft-stop common) — "
                "short GIF is honesty, not an Ip-collapse claim."
            )
        else:
            items.append(
                f"Evolutive early_stop={es}{steps_bit} — see evolutive_meta.json / limitations."
            )
    if isinstance(evo_meta, dict) and evo_meta.get("clamp_ip_to_measured") is True:
        items.append(
            "Evolutive clamp_ip_to_measured=true: Ip residual is a clamp tautology — "
            "prefer Raxis drift / early_stop for soft physics honesty."
        )
    if isinstance(evo_meta, dict) and str(evo_meta.get("ic_coil_currents") or "") == "inverse_dump":
        items.append(
            "Evolutive ic_coil_currents=inverse_dump (DEMO/shape-IC) — measured V may "
            "disagree with shape-optimised I at t0; science default is measured_pf."
        )
    return {
        "available": bool(items),
        "n": len(items),
        "items": items,
        "expect_gif_mismatch_vs_archive_dn": expect_mismatch,
        "lcfs_mean_nn_symmetric_m": lcfs_m,
        "high_lcfs_residual": high_lcfs,
        "forward_window_currents": win_curr if fwd.get("available") else None,
        "profile_trajectory": {
            "fit_mode_used": traj.get("fit_mode_used"),
            "alphas_from_pprime": traj.get("alphas_from_pprime"),
            "status": traj.get("status"),
        },
        "note": (
            "Presentation / GIF-expectation advisories only; do not invent ρ/passives "
            "to force DN visuals. Evolutive stays soft-stop until cited resistivity exists."
        ),
    }


def build_science_audit(run_dir: Path) -> Dict[str, Any]:
    """Write 01_summary/science_audit.json and return the audit object."""
    run_dir = Path(run_dir)
    audit: Dict[str, Any] = {
        "version": "1.5",
        "reconstruction_quality": reconstruct_quality(run_dir),
        "inverse_shape_gate": inverse_shape_gate_summary(run_dir),
        "forward_gate": forward_gate_summary(run_dir),
        "profile_trajectory": profile_trajectory_audit(run_dir),
        "presentation_advisories": presentation_advisories(run_dir),
        "evolutive_ip": score_evolutive_ip(run_dir),
        "evolutive_raxis_drift": score_evolutive_raxis_drift(run_dir),
        "ohmic_drive": ohmic_drive_inventory(run_dir),
        "phase_timeline": phase_timeline_from_window(run_dir),
        "passive_resistivity": passive_resistivity_status(run_dir),
        "presentation_note": (
            "Equilibrium GIFs under 03_reconstruction/presentation/ and "
            "03_reconstruction/evolutive/ (or legacy presentation/, evolutive/) are annex visuals; "
            "scientific review should start from residuals, Ip match (or Raxis drift when "
            "clamp_ip tautology), solve_mode, inverse_shape_gate, and forward_gate "
            "(measured-PF Forward ≠ Inverse DN)."
        ),
    }
    # Persist phase timeline under inputs for tooling
    phases = audit["phase_timeline"]
    if phases.get("available"):
        (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
        (run_dir / "inputs" / "phase_timeline.json").write_text(
            json.dumps(phases, indent=2) + "\n", encoding="utf-8"
        )
    out_dir = run_dir / "01_summary"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "science_audit.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8"
    )
    return audit
