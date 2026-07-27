"""Optional evolutive driven by planner planned_voltages (ADR-004 P2; default off)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Type

import numpy as np
import pandas as pd


def prepare_plan_voltages_csv(
    *,
    run_dir: Path,
    inputs_dir: Path,
) -> Path:
    """Write inputs/pf_voltages_from_plan.csv aligned to measured voltage columns."""
    plan_v = Path(run_dir) / "07_planner" / "planned_voltages.csv"
    if not plan_v.is_file():
        raise FileNotFoundError(f"missing planned voltages: {plan_v}")
    meas = Path(inputs_dir) / "pf_voltages.csv"
    plan_df = pd.read_csv(plan_v)
    if "time" not in plan_df.columns:
        raise ValueError("planned_voltages.csv missing time column")
    t_plan = plan_df["time"].to_numpy(dtype=float)
    if meas.is_file():
        meas_df = pd.read_csv(meas)
        if "time" not in meas_df.columns:
            raise ValueError("pf_voltages.csv missing time column")
        t_meas = meas_df["time"].to_numpy(dtype=float)
        out = pd.DataFrame({"time": t_plan})
        for c in meas_df.columns:
            if c == "time":
                continue
            if c in plan_df.columns:
                out[c] = plan_df[c].to_numpy(dtype=float)
            else:
                # Channels not planned (e.g. divertor defaults): keep measured interp.
                out[c] = np.interp(
                    t_plan, t_meas, meas_df[c].to_numpy(dtype=float)
                )
    else:
        out = plan_df.copy()
    dest = Path(inputs_dir) / "pf_voltages_from_plan.csv"
    out.to_csv(dest, index=False)
    return dest


def run_evolutive_from_plan_stage(
    *,
    run_dir: Path,
    cfg: Any,
    repo_root: Path,
    inputs_dir: Path,
    freegsnke_runner_cls: Type[Any],
) -> Dict[str, Any]:
    """Execute evolutive_run.py with planned voltages → 03_reconstruction/evolutive_plan."""
    run_dir = Path(run_dir)
    inputs_dir = Path(inputs_dir)
    evo_script = run_dir / "evolutive_run.py"
    out: Dict[str, Any] = {
        "ok": False,
        "note": None,
        "path": "03_reconstruction/evolutive_plan",
        "blocking_error": None,
    }
    if not evo_script.is_file():
        out["note"] = "missing_evolutive_run.py"
        out["blocking_error"] = "evolutive_from_plan_missing_script"
        return out
    if not (run_dir / "inverse_dump.pkl").is_file():
        out["note"] = "inverse_not_ok"
        out["blocking_error"] = (
            "evolutive_from_plan_requires_successful_inverse: inverse_dump.pkl missing"
        )
        return out
    try:
        volt_path = prepare_plan_voltages_csv(run_dir=run_dir, inputs_dir=inputs_dir)
    except Exception as e:
        out["note"] = f"plan_voltages_prep_failed:{type(e).__name__}"
        out["blocking_error"] = f"evolutive_from_plan_failed: {type(e).__name__}: {e}"
        return out

    out_dir = run_dir / "03_reconstruction" / "evolutive_plan"
    out_dir.mkdir(parents=True, exist_ok=True)

    evo_timeout = getattr(cfg, "freegsnke_script_timeout_s", 1200)
    evo_auth_path = inputs_dir / "evolutive_authority" / "evolutive_authority.json"
    if evo_auth_path.exists():
        try:
            evo_timeout = float(
                json.loads(evo_auth_path.read_text(encoding="utf-8")).get(
                    "script_timeout_s", evo_timeout
                )
            )
        except Exception:
            pass

    runner = freegsnke_runner_cls(
        python_exe=getattr(cfg, "freegsnke_python", None),
        timeout_s=evo_timeout,
        repo_root=repo_root,
        env={
            "MAST_FREEGSNKE_EVOLUTIVE_VOLTAGES": str(volt_path.resolve()),
            "MAST_FREEGSNKE_EVOLUTIVE_OUT": str(out_dir.resolve()),
        },
    )
    er = runner.run_script(evo_script, run_dir=run_dir, label="evolutive_from_plan")
    out["duration_s"] = er.duration_s
    out["returncode"] = er.returncode
    out["error_hint"] = er.error_hint
    try:
        out["voltages"] = str(volt_path.relative_to(run_dir))
    except ValueError:
        out["voltages"] = str(volt_path)
    meta = {
        "drive": "planned_voltages",
        "voltages_csv": str(volt_path),
        "out_dir": str(out_dir),
        "script_ok": bool(er.ok),
        "note": (
            "Optional A/B evolutive: FreeGSNKE driven by 07_planner/planned_voltages "
            "(not measured pf_voltages). Default off (execute_evolutive_from_plan)."
        ),
    }
    (out_dir / "evolutive_from_plan_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    if not er.ok:
        out["ok"] = False
        out["note"] = er.error_hint or "evolutive_from_plan_failed"
        # Soft warning only — plan-driven evolutive is diagnostic A/B, not happy-path gate.
        out["blocking_error"] = None
        out["warn"] = "evolutive_from_plan_failed (see logs/evolutive_from_plan.stderr.txt)"
        return out
    out["ok"] = True
    out["note"] = "planned_voltages_drive"
    ip_score = score_evolutive_ip_at(
        run_dir, evolutive_relpath="03_reconstruction/evolutive_plan"
    )
    out["ip_score"] = ip_score
    return out


def score_evolutive_ip_at(
    run_dir: Path,
    *,
    evolutive_relpath: str = "03_reconstruction/evolutive",
) -> Dict[str, Any]:
    """Compare evolutive history Ip(t) to measured inputs/ip.csv (honest soft-fail)."""
    run_dir = Path(run_dir)
    report: Dict[str, Any] = {
        "ok": False,
        "evolutive_relpath": evolutive_relpath,
        "n": 0,
        "rms_A": None,
        "mae_A": None,
        "max_abs_A": None,
        "rms_rel": None,
        "errors": [],
    }
    out_csv = run_dir / evolutive_relpath / "ip_residual.csv"
    # Prefer already-written residual CSV (UI tab switches) — avoid re-scoring every open.
    if out_csv.is_file():
        try:
            import pandas as pd
            import numpy as np

            rdf = pd.read_csv(out_csv)
            if "residual_A" in rdf.columns and "Ip_measured" in rdf.columns:
                resid = rdf["residual_A"].to_numpy(dtype=float)
                ip_meas = rdf["Ip_measured"].to_numpy(dtype=float)
                mask = np.isfinite(resid) & np.isfinite(ip_meas)
                resid, ip_meas = resid[mask], ip_meas[mask]
                if resid.size >= 2:
                    rms = float(np.sqrt(np.mean(resid**2)))
                    mae = float(np.mean(np.abs(resid)))
                    max_abs = float(np.max(np.abs(resid)))
                    scale = float(np.mean(np.abs(ip_meas)))
                    rms_rel = float(rms / scale) if scale > 0.0 else None
                    report.update(
                        {
                            "ok": True,
                            "n": int(resid.size),
                            "rms_A": rms,
                            "mae_A": mae,
                            "max_abs_A": max_abs,
                            "rms_rel": rms_rel,
                            "residual_csv": f"{evolutive_relpath}/ip_residual.csv",
                            "from_cached_csv": True,
                        }
                    )
                    return report
        except Exception:
            pass

    hist = run_dir / evolutive_relpath / "history.csv"
    ip_path = run_dir / "inputs" / "ip.csv"
    if not hist.is_file():
        report["errors"].append("missing_evolutive_history_csv")
        return report
    if not ip_path.is_file():
        report["errors"].append("missing_inputs_ip_csv")
        return report
    try:
        import pandas as pd

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
    import numpy as np

    t_h = hdf["t_abs"].to_numpy(dtype=float)
    ip_h = hdf["Ip"].to_numpy(dtype=float)
    mask = np.isfinite(t_h) & np.isfinite(ip_h)
    if "step_ok" in hdf.columns:
        mask = mask & np.asarray([bool(x) for x in hdf["step_ok"].to_numpy()])
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
    order = np.argsort(t_m)
    ip_meas = np.interp(t_h, t_m[order], ip_m[order])
    resid = ip_h - ip_meas
    rms = float(np.sqrt(np.mean(resid**2)))
    mae = float(np.mean(np.abs(resid)))
    max_abs = float(np.max(np.abs(resid)))
    scale = float(np.mean(np.abs(ip_meas)))
    rms_rel = float(rms / scale) if scale > 0.0 else None
    out_csv.parent.mkdir(parents=True, exist_ok=True)
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
            "residual_csv": f"{evolutive_relpath}/ip_residual.csv",
        }
    )
    return report


def load_evolutive_ab_compare(run_dir: Path) -> Dict[str, Any]:
    """Measured-V vs plan-V evolutive A/B within one shot (read-only)."""
    run_dir = Path(run_dir)
    meas = score_evolutive_ip_at(run_dir, evolutive_relpath="03_reconstruction/evolutive")
    plan = score_evolutive_ip_at(run_dir, evolutive_relpath="03_reconstruction/evolutive_plan")
    meta_path = run_dir / "03_reconstruction/evolutive_plan/evolutive_from_plan_meta.json"
    meta = None
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = None
    out: Dict[str, Any] = {
        "measured_voltages": meas,
        "planned_voltages": plan,
        "plan_meta_present": bool(meta),
        "plan_script_ok": bool(meta.get("script_ok")) if isinstance(meta, dict) else None,
        "plan_drive": meta.get("drive") if isinstance(meta, dict) else None,
    }
    if meas.get("ok") and plan.get("ok"):
        out["delta_rms_A"] = float(plan["rms_A"]) - float(meas["rms_A"])
        out["detail"] = (
            f"measured-V evo rms={meas['rms_A']:.1f} A; "
            f"plan-V evo rms={plan['rms_A']:.1f} A; "
            f"Δrms={out['delta_rms_A']:.1f} A"
        )
    elif meas.get("ok"):
        out["detail"] = (
            f"measured-V evo rms={meas['rms_A']:.1f} A; "
            "plan-V evo not available (execute_evolutive_from_plan)"
        )
    else:
        out["detail"] = "Evolutive A/B unavailable — run execute_evolutive + execute_evolutive_from_plan"
    return out
