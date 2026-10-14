from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import pandas as pd

from .schema import WindowDef
from .window_library import generate_window_library
from .phase_segmentation import segment_phases_from_window
from .scenario_generation import generate_scenarios_for_window
from .scenario_execution import run_scenario
from .analysis import load_scenario_metrics, select_robust_choice, stability_tiering, continuity_metrics
from .phase_consistency import compute_phase_consistency
from .attribution import sensitivity_attribution, dominant_failure_modes_markdown
from .plotting import generate_plots
from ..diagnostic_contracts import load_contracts

# Deterministic worst-first tier ordering (unknown tiers rank below GREEN).
_TIER_RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2}


def write_root_stability_rollup(out_root: Path, per_window_summary: List[Dict[str, Any]]) -> Path:
    """Write the root-level ``stability_scorecard.json`` rollup for a robustness run.

    Production robustness_run writes stability scorecards per window
    (``windows/<id>/stability_scorecard.json``), while the v5 corpus schema
    (``corpus.schema.REQUIRED_ROBUSTNESS_FILES``) and ``corpus.atlas`` read a
    root-level scorecard. This deterministic rollup aggregates the worst window
    tier and the maximum relative degradation so corpus-build works on genuine
    robustness-run output instead of a fabricated file.
    """
    rows = sorted(
        (
            {
                "window_id": str(r.get("window_id")),
                "tier": r.get("tier"),
                "relative_degradation": r.get("relative_degradation"),
            }
            for r in per_window_summary
        ),
        key=lambda r: r["window_id"],
    )
    tiers = [r["tier"] for r in rows if r["tier"] in _TIER_RANK]
    rels = [
        float(r["relative_degradation"])
        for r in rows
        if isinstance(r["relative_degradation"], (int, float)) and not isinstance(r["relative_degradation"], bool)
    ]
    payload: Dict[str, Any] = {
        "ok": bool(rows),
        "method": "worst_window_tier_max_relative_degradation",
        "tier": max(tiers, key=lambda t: _TIER_RANK[t]) if tiers else None,
        "relative_degradation": max(rels) if rels else 0.0,
        "n_windows": len(rows),
        "windows": rows,
    }
    path = out_root / "stability_scorecard.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path

def robustness_run(
    run_dir: Path,
    policy: str = "maximin",
    dt_grid: Optional[List[float]] = None,
    expand_grid: Optional[List[float]] = None,
    green: float = 0.05,
    yellow: float = 0.15,
    allow_sign_toggle: bool = False,
) -> Path:
    """
    Execute v4 multi-window robustness analysis inside an existing run directory.

    Writes into:
      <run_dir>/robustness_v4/
    """
    run_dir = run_dir.resolve()
    inputs_dir = run_dir / "inputs"
    win_path = inputs_dir / "window.json"
    if not win_path.exists():
        raise FileNotFoundError(f"baseline window.json not found: {win_path}")

    base_win = json.loads(win_path.read_text())
    t0 = float(base_win["t_start"])
    t1 = float(base_win["t_end"])

    # contracts: prefer resolved contracts written during run
    resolved_contracts = run_dir / "contracts" / "diagnostic_contracts.resolved.json"
    if not resolved_contracts.exists():
        raise FileNotFoundError(f"resolved contracts not found: {resolved_contracts}")

    contracts = load_contracts(resolved_contracts)
    # windows
    windows = generate_window_library(
        t_start=t0,
        t_end=t1,
        dt_grid=tuple(dt_grid) if dt_grid is not None else (-0.02, -0.01, 0.0, 0.01, 0.02),
        expand_grid=tuple(expand_grid) if expand_grid is not None else (0.0, 0.01),
    )

    out_root = run_dir / "robustness_v4"
    out_root.mkdir(parents=True, exist_ok=True)

    # record window library
    win_obj = {"baseline_window": {"t_start": t0, "t_end": t1}, "windows": [w.to_obj() for w in windows]}
    (out_root / "window_library.json").write_text(json.dumps(win_obj, indent=2, sort_keys=True))

    # phase timeline from baseline window (for narrative)
    baseline_def = WindowDef(window_id="baseline", t_start=t0, t_end=t1, note="from inputs/window.json")
    phases = segment_phases_from_window(baseline_def)
    (out_root / "phase_timeline.json").write_text(json.dumps(phases, indent=2, sort_keys=True))

    per_window_summary: List[Dict[str, Any]] = []

    for wdef in windows:
        wdir = out_root / "windows" / wdef.window_id
        wdir.mkdir(parents=True, exist_ok=True)

        # scenarios
        scenarios = generate_scenarios_for_window(
            wdef, contracts,
            include_contract_perturbations=True,
            include_leave_one_out=True,
            allow_sign_toggle=allow_sign_toggle,
        )
        (wdir / "scenario_library.json").write_text(json.dumps([s.to_obj() for s in scenarios], indent=2, sort_keys=True))

        # execute
        for s in scenarios:
            run_scenario(wdir, wdef, s, contracts)

        # aggregate
        df = load_scenario_metrics(wdir / "scenarios")
        df.to_csv(wdir / "aggregated_metrics.csv", index=False)

        choice = select_robust_choice(df, policy=policy)
        (wdir / "robust_choice.json").write_text(json.dumps(choice, indent=2, sort_keys=True))

        stable = stability_tiering(df, green=green, yellow=yellow)
        (wdir / "stability_scorecard.json").write_text(json.dumps(stable, indent=2, sort_keys=True))

        per_window_summary.append({
            "window_id": wdef.window_id,
            "t_start": wdef.t_start,
            "t_end": wdef.t_end,
            "policy": choice.get("policy"),
            "scenario_id": choice.get("scenario_id"),
            "score_total": float(choice.get("score_total", float("inf"))),
            "tier": stable.get("tier"),
            "relative_degradation": stable.get("relative_degradation"),
        })

    # continuity and global selection across windows
    dfw = pd.DataFrame(per_window_summary).sort_values(["window_id"], kind="mergesort")
    dfw.to_csv(out_root / "per_window_summary.csv", index=False)

    cont = continuity_metrics(per_window_summary)
    cont.to_csv(out_root / "continuity_metrics.csv", index=False)

    # v4.1: phase-consistency classification (regime-aware, deterministic)
    per_window_df = pd.DataFrame(per_window_summary).sort_values(["window_id"], kind="mergesort")
    phase_consistency = compute_phase_consistency(per_window_df, phases)
    (out_root / "phase_consistency_scorecard.json").write_text(json.dumps(phase_consistency, indent=2, sort_keys=True))
    pcs_md = ["# Phase Consistency Summary", ""]
    if phase_consistency.get("ok"):
        pcs_md += [f"- global_label: **{phase_consistency.get('global_label')}**", ""]
        for ph in phase_consistency.get("phases", []):
            if not ph.get("ok"):
                pcs_md.append(f"- {ph.get('phase')}: (no windows)")
                continue
            pcs_md.append(f"- {ph['phase']}: **{ph['label']}** (dominant_fraction={ph['dominant_fraction']:.2f}, rel_drift={ph['relative_score_drift']:.2f}, flip_rate={ph['flip_rate']:.2f})")
    (out_root / "phase_consistency_summary.md").write_text("\n".join(pcs_md) + "\n")

    # v4.1: sensitivity attribution ledger (family dominance + top damage scenarios)
    attrib = sensitivity_attribution(out_root)
    (out_root / "sensitivity_attribution.json").write_text(json.dumps(attrib, indent=2, sort_keys=True))
    (out_root / "dominant_failure_modes.md").write_text(dominant_failure_modes_markdown(attrib) + "\n")

    # v4.1: deterministic plots + plot manifest (hash-locked)
    generate_plots(out_root)


    # global robust choice: choose window whose chosen score_total is minimal (deterministic tie-break by window_id)
    if not dfw.empty:
        dfw2 = dfw.sort_values(["score_total", "window_id"], ascending=[True, True], kind="mergesort")
        best = dfw2.iloc[0].to_dict()
        global_choice = {"ok": True, "method": "min_score_total_over_window_choices", "best_window": best}
    else:
        global_choice = {"ok": False, "error": "no window summaries"}
    (out_root / "global_robust_choice.json").write_text(json.dumps(global_choice, indent=2, sort_keys=True))

    # Root-level stability rollup: corpus.schema / corpus.atlas require
    # robustness_v4/stability_scorecard.json, but per-window scorecards alone
    # left corpus-build unable to index genuine robustness-run output.
    # Deterministic aggregation (worst window tier, max relative degradation).
    write_root_stability_rollup(out_root, per_window_summary)

    # stability summary markdown
    md = ["# Robustness v4 Summary", "", f"- policy: `{policy}`", f"- windows: {len(windows)}", ""]
    if global_choice.get("ok"):
        bw = global_choice["best_window"]
        md += [f"## Global choice", "", f"- window_id: `{bw['window_id']}`", f"- score_total: {bw['score_total']}", f"- tier: {bw.get('tier')}", ""]
    (out_root / "robust_summary.md").write_text("\n".join(md))

    return out_root
