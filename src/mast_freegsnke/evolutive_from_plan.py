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
    return out
