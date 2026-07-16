"""
Physics audit runner: per-window closure tests + residual budget + physics tier.
Purely diagnostic, deterministic, and hash-locked.
© 2026 Afshin Arjhangmehr
"""

from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import json
import pandas as pd

from .schema import PhysicsAuditConfig, ResidualBudget, ClosureTestResult, PhysicsScorecard
from .closures import load_window_metrics, closure_test_continuity_drift, closure_test_worstcase_spread, closure_test_regime_boundary_spike
from .budget import build_residual_budget_from_window, sanity_check_budget, budget_total

def _read_json(p: Path) -> Dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, sort_keys=True)

def _tier(value: float, green: float, yellow: float) -> str:
    if value <= green:
        return "PHYSICS-GREEN"
    if value <= yellow:
        return "PHYSICS-YELLOW"
    return "PHYSICS-RED"

def run_physics_audit(run_dir: Path, config: PhysicsAuditConfig) -> PhysicsScorecard:
    run_dir = Path(run_dir)
    root = run_dir / "robustness_v4"
    if not root.exists():
        raise FileNotFoundError(f"Expected robustness_v4 directory at: {root}")

    phase_timeline_path = root / "phase_timeline.json"
    if not phase_timeline_path.exists():
        raise FileNotFoundError(f"Missing phase timeline: {phase_timeline_path}")
    phase_timeline = _read_json(phase_timeline_path)
    phases = phase_timeline.get("phases", [])
    # phases: list of {name,start,end}
    phase_bounds = [(float(p["start"]), float(p["end"])) for p in phases if "start" in p and "end" in p]

    windows_dir = root / "windows"
    if not windows_dir.exists():
        raise FileNotFoundError(f"Missing windows directory: {windows_dir}")

    per_window_rows = []
    per_test_all: List[ClosureTestResult] = []

    # try to use per_window_summary.csv for window ordering and midpoints if exists
    pws = root / "per_window_summary.csv"
    window_meta = None
    if pws.exists():
        window_meta = pd.read_csv(pws)

    prev_score = None
    max_violation = 0.0

    for wdir in sorted([p for p in windows_dir.iterdir() if p.is_dir()], key=lambda p: p.name):
        payload = load_window_metrics(wdir)

        # window midpoint (if available)
        mid_t = None
        if window_meta is not None:
            row = window_meta[window_meta["window_id"] == wdir.name]
            if len(row) == 1 and "t_mid" in row.columns:
                try:
                    mid_t = float(row.iloc[0]["t_mid"])
                except Exception:
                    mid_t = None

        rc = payload.get("robust_choice") or {}
        curr_score = None
        if config.primary_metric in rc:
            try:
                curr_score = float(rc[config.primary_metric])
            except Exception:
                curr_score = None
        elif "score_total" in rc:
            try:
                curr_score = float(rc["score_total"])
            except Exception:
                curr_score = None

        drift = closure_test_continuity_drift(prev_score, curr_score)
        spread = closure_test_worstcase_spread(payload.get("stability_scorecard") or {})

        # boundary spike uses nearest phase bounds; choose the phase containing mid_t if possible, else first.
        spike = None
        if phase_bounds and mid_t is not None and drift is not None:
            chosen = phase_bounds[0]
            for a, b in phase_bounds:
                if a <= mid_t <= b:
                    chosen = (a, b)
                    break
            spike = closure_test_regime_boundary_spike(mid_t, chosen, drift)

        tests: List[Tuple[str, Optional[float]]] = [
            ("continuity_drift", drift),
            ("worstcase_spread", spread),
            ("phase_boundary_spike", spike),
        ]

        # Normalize missing -> 0 (explicit), but keep details
        test_results = []
        for name, val in tests:
            v = float(val) if val is not None else 0.0
            tier = _tier(v, config.physics_green, config.physics_yellow)
            max_violation = max(max_violation, v)
            test_results.append(ClosureTestResult(
                name=name,
                value=v,
                threshold_green=config.physics_green,
                threshold_yellow=config.physics_yellow,
                tier=tier,
                details={
                    "window_id": wdir.name,
                    "mid_t": mid_t,
                    "prev_score": prev_score,
                    "curr_score": curr_score,
                    "raw": None if val is None else float(val),
                }
            ))

        # residual budget per window
        buckets = build_residual_budget_from_window(payload, primary_metric=config.primary_metric)
        ok = sanity_check_budget(buckets)
        total = budget_total(buckets)
        rb = ResidualBudget(
            buckets=buckets,
            total=total,
            sanity_ok=ok,
            notes=(
                "Derived from robustness_v4 artifacts; UNMEASURED buckets omitted: "
                "coil_mapping,diagnostic_subset,contract_scale"
                if ok
                else "Sanity check failed"
            ),
        )

        # collect per window summary row
        per_window_rows.append({
            "window_id": wdir.name,
            "t_mid": mid_t,
            "primary_metric": config.primary_metric,
            "score": curr_score,
            "max_test_violation": max([tr.value for tr in test_results]) if test_results else 0.0,
            "budget_total": total,
            "budget_sanity_ok": ok,
        })

        # write per-window artifacts
        _write_json(wdir / "closure_tests.json", {"tests": [tr.to_dict() for tr in test_results], "config": config.to_dict()})
        _write_json(wdir / "residual_budget.json", rb.to_dict())

        per_test_all.extend(test_results)
        prev_score = curr_score

    # global tier
    global_tier = _tier(max_violation, config.physics_green, config.physics_yellow)

    # global residual budget: aggregate totals deterministically from per-window budgets
    # Use simple sum of bucket means to avoid window count dependence? We'll use mean per bucket, then sum.
    if per_window_rows:
        # read back budgets from windows
        bucket_sums = {}
        n = 0
        for wdir in sorted([p for p in windows_dir.iterdir() if p.is_dir()], key=lambda p: p.name):
            rb_path = wdir / "residual_budget.json"
            if rb_path.exists():
                rbj = _read_json(rb_path)
                buckets = rbj.get("buckets", {})
                for k, v in buckets.items():
                    bucket_sums[k] = bucket_sums.get(k, 0.0) + float(v)
                n += 1
        if n == 0:
            bucket_means = {}
        else:
            bucket_means = {k: v / n for k, v in bucket_sums.items()}
    else:
        bucket_means = {}

    okg = sanity_check_budget(bucket_means)
    totalg = budget_total(bucket_means) if bucket_means else 0.0
    global_rb = ResidualBudget(buckets=bucket_means, total=totalg, sanity_ok=okg, notes="Global mean bucket ledger across windows" if okg else "Sanity check failed")

    scorecard = PhysicsScorecard(
        tier=global_tier,
        max_violation=max_violation,
        primary_metric=config.primary_metric,
        per_test=per_test_all,
        residual_budget=global_rb,
        config_hash=config.hash(),
    )

    # write global artifacts
    out_root = root / "physics_audit"
    _write_json(out_root / "physics_consistency_scorecard.json", scorecard.to_dict())
    pd.DataFrame(per_window_rows).to_csv(out_root / "per_window_physics.csv", index=False)
    # summary markdown
    md = []
    md.append(f"# Physics Consistency Summary\n\n")
    md.append(f"Tier: **{scorecard.tier}**\n\n")
    md.append(f"Max violation: `{scorecard.max_violation:.6g}` (green<= {config.physics_green}, yellow<= {config.physics_yellow})\n\n")
    md.append(f"Primary metric: `{config.primary_metric}`\n\n")
    md.append("## Global Residual Budget (mean across windows)\n\n")
    for k in sorted(scorecard.residual_budget.buckets.keys()):
        md.append(f"- {k}: {scorecard.residual_budget.buckets[k]:.6g}\n")
    md.append("\n")
    (out_root / "physics_consistency_summary.md").write_text("".join(md), encoding="utf-8")
    return scorecard
