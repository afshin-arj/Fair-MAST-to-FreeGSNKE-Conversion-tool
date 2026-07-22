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
    """
    run_dir = Path(run_dir)
    report: Dict[str, Any] = {
        "ok": False,
        "n": 0,
        "rms_A": None,
        "mae_A": None,
        "max_abs_A": None,
        "rms_rel": None,
        "errors": [],
    }
    hist = run_dir / "evolutive" / "history.csv"
    ip_path = run_dir / "inputs" / "ip.csv"
    if not hist.exists():
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
    out_csv = run_dir / "evolutive" / "ip_residual.csv"
    pd.DataFrame(
        {
            "t_abs": t_h,
            "Ip_evolutive": ip_h,
            "Ip_measured": ip_meas,
            "residual_A": resid,
        }
    ).to_csv(out_csv, index=False)
    report.update(
        {
            "ok": True,
            "n": int(t_h.size),
            "rms_A": rms,
            "mae_A": mae,
            "max_abs_A": max_abs,
            "rms_rel": rms_rel,
            "residual_csv": "evolutive/ip_residual.csv",
            "note": (
                "Ip_measured is FAIR-MAST Level-2 ip.csv interpolated to evolutive t_abs; "
                "not an invented metrology channel."
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


def build_science_audit(run_dir: Path) -> Dict[str, Any]:
    """Write 01_summary/science_audit.json and return the audit object."""
    run_dir = Path(run_dir)
    audit: Dict[str, Any] = {
        "version": "1.0",
        "reconstruction_quality": reconstruct_quality(run_dir),
        "evolutive_ip": score_evolutive_ip(run_dir),
        "ohmic_drive": ohmic_drive_inventory(run_dir),
        "phase_timeline": phase_timeline_from_window(run_dir),
        "passive_resistivity": passive_resistivity_status(run_dir),
        "presentation_note": (
            "Equilibrium GIFs under presentation/ and evolutive/ are annex visuals; "
            "scientific review should start from residuals, Ip match, and solve_mode."
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
