"""
Residual budget ledger computed from existing robustness/stability outputs.
The ledger is a deterministic decomposition, not an optimizer.
© 2026 Afshin Arjhangmehr
"""

from __future__ import annotations
from typing import Dict, Any, Optional
import math

def build_residual_budget_from_window(window_payload: Dict[str, Any], primary_metric: str = "score_total") -> Dict[str, float]:
    """
    Deterministic bucketization rules.
    We map available artifacts into buckets.
    All buckets are non-negative, normalized values.

    Buckets:
      - equilibrium: based on score_total (or primary_metric) if available
      - robustness_worstcase: relative_degradation from stability_scorecard if available
      - continuity: delta score from robust_choice if available
    """
    buckets: Dict[str, float] = {}

    # (1) equilibrium proxy: use robust_choice[primary_metric] if present
    rc = window_payload.get("robust_choice") or {}
    eq = rc.get(primary_metric, rc.get("score_total"))
    try:
        eqv = float(eq) if eq is not None else 0.0
    except Exception:
        eqv = 0.0
    buckets["equilibrium"] = max(eqv, 0.0)

    # (2) robustness spread proxy
    sc = window_payload.get("stability_scorecard") or {}
    try:
        rd = float(sc.get("relative_degradation")) if sc.get("relative_degradation") is not None else 0.0
    except Exception:
        rd = 0.0
    buckets["robustness_worstcase"] = max(rd, 0.0)

    # (3) continuity proxy
    try:
        ds = float(rc.get("delta_score_prev")) if rc.get("delta_score_prev") is not None else 0.0
    except Exception:
        ds = 0.0
    buckets["continuity"] = max(abs(ds), 0.0)

    # (4) Unmeasured buckets intentionally OMITTED (not 0.0 — zeros look like evidence).
    # Unmeasured: coil_mapping, diagnostic_subset, contract_scale

    return buckets

def sanity_check_budget(buckets: Dict[str, float]) -> bool:
    if not buckets:
        return False
    for k, v in buckets.items():
        if v is None or not isinstance(v, (int, float)) or math.isnan(v) or v < 0:
            return False
    return True

def budget_total(buckets: Dict[str, float]) -> float:
    return float(sum(buckets.values()))
