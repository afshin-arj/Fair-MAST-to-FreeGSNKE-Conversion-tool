"""Honest Inverse shape vs archive/null targets (never invent metrology).

FreeGSNKE ``Inverse_optimizer`` stops on GS residual + relative ψ update;
constraint / boundary loss is recorded but not a stop condition. This module
scores solved total-ψ critical points against declared Inverse targets so
``converged`` is not misread as DN shape success.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


def _finite(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or abs(v) == float("inf"):
        return None
    return v


def _as_rz_list(null_points: Any) -> List[Tuple[float, float]]:
    """BoundarySpec null_points [[R...],[Z...]] → [(R,Z), ...]."""
    if not isinstance(null_points, (list, tuple)) or len(null_points) < 2:
        return []
    try:
        rr = [float(v) for v in null_points[0]]
        zz = [float(v) for v in null_points[1]]
    except (TypeError, ValueError):
        return []
    if len(rr) != len(zz) or len(rr) < 1:
        return []
    return list(zip(rr, zz))


def critical_points_from_total_psi(eq: Any, *, ip: float) -> Dict[str, Any]:
    """O/X from total ψ (plasma+coils). ``plasma_psi`` alone yields false 0-X."""
    import numpy as np

    out: Dict[str, Any] = {
        "ok": False,
        "n_opt": 0,
        "n_xpt": 0,
        "opt": [],
        "xpt": [],
        "psi_axis": None,
        "psi_bndry": None,
        "error": None,
    }
    try:
        psi = eq.psi() if callable(getattr(eq, "psi", None)) else getattr(eq, "psi", None)
        if psi is None:
            out["error"] = "eq.psi_unavailable"
            return out
        psi_arr = np.asarray(psi, dtype=float)
        from freegs4e import critical

        opt, xpt = critical.find_critical(eq.R, eq.Z, psi_arr, None, float(ip))
        if opt is not None:
            for row in opt:
                out["opt"].append([float(row[0]), float(row[1]), float(row[2])])
            out["n_opt"] = len(out["opt"])
            if out["opt"]:
                out["psi_axis"] = float(out["opt"][0][2])
        if xpt is not None:
            for row in xpt:
                out["xpt"].append([float(row[0]), float(row[1]), float(row[2])])
            out["n_xpt"] = len(out["xpt"])
            if out["xpt"]:
                out["psi_bndry"] = float(out["xpt"][0][2])
        out["ok"] = out["n_opt"] > 0
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def score_inverse_shape(
    *,
    eq: Any,
    null_points: Any,
    ip: float,
    constrain_loss_final: Optional[float] = None,
    null_topology: Optional[str] = None,
    acceptance: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Score solved critical points vs declared Inverse null targets.

    When ``acceptance`` (InverseShapeAcceptanceSpec asdict) is provided and
    enabled, ``shape_accepted`` / ``shape_status`` use those declared thresholds.
    Without acceptance authority, keeps soft honesty labels only.
    """
    targets = _as_rz_list(null_points)
    crit = critical_points_from_total_psi(eq, ip=float(ip))
    topology = str(null_topology or "").strip().lower()
    if not topology:
        topology = "double_null" if len(targets) >= 3 else ("single_null" if len(targets) >= 2 else "unknown")

    solved_x = [(float(r), float(z)) for r, z, _p in crit.get("xpt") or []]
    solved_o = [(float(r), float(z)) for r, z, _p in crit.get("opt") or []]

    def _nearest(pt: Tuple[float, float], cloud: Sequence[Tuple[float, float]]) -> Optional[float]:
        if not cloud:
            return None
        return float(min(math.hypot(pt[0] - c[0], pt[1] - c[1]) for c in cloud))

    target_scores: List[Dict[str, Any]] = []
    # Convention: index0 = primary X, index1 = O, rest = further X
    for i, (tr, tz) in enumerate(targets):
        role = "x" if i != 1 else "o"
        cloud = solved_o if role == "o" else solved_x
        d = _nearest((tr, tz), cloud)
        target_scores.append(
            {
                "role": role,
                "index": i,
                "target_r": tr,
                "target_z": tz,
                "nearest_solved_dist_m": d,
            }
        )

    psi_x = [float(p) for _r, _z, p in (crit.get("xpt") or [])]
    psi_span = None
    if len(psi_x) >= 2:
        psi_span = float(max(psi_x) - min(psi_x))

    dn_claimed = topology in {"double_null", "dn"} or len(targets) >= 3
    acc = dict(acceptance or {})
    acc_enabled = bool(acc.get("enabled", False)) if acceptance is not None else False
    min_x_dn = int(acc.get("min_xpoints_for_dn", 2) or 2)
    max_x_dist = float(acc.get("max_x_target_dist_m", 0.05) or 0.05)
    max_o_dist = float(acc.get("max_o_target_dist_m", 0.05) or 0.05)
    max_loss = acc.get("max_constrain_loss", None)
    max_span = acc.get("max_xpt_psi_span", None)
    on_fail = str(acc.get("on_fail", "label_only") or "label_only")

    n_xpt = int(crit.get("n_xpt") or 0)
    dn_x_ok = (not dn_claimed) or n_xpt >= min_x_dn

    loss = _finite(constrain_loss_final)
    reasons: List[str] = []

    if not crit.get("ok"):
        shape_status = "critical_unavailable"
        reasons.append("critical_unavailable")
    elif dn_claimed and not dn_x_ok:
        shape_status = "dn_missing_xpoints"
        reasons.append(f"n_xpt={n_xpt}<{min_x_dn}")
    else:
        # Distance / loss / psi-span checks
        for s in target_scores:
            d = s.get("nearest_solved_dist_m")
            if d is None:
                reasons.append(f"missing_solved_{s['role']}_{s['index']}")
                continue
            lim = max_o_dist if s.get("role") == "o" else max_x_dist
            # Soft defaults when acceptance disabled: keep prior 0.08 X heuristic
            if not acc_enabled:
                lim = 0.08 if s.get("role") == "x" else max_o_dist
            if float(d) > float(lim):
                reasons.append(
                    f"{s['role']}_{s['index']}_dist={float(d):.4f}>{float(lim):.4f}"
                )
        loss_lim = float(max_loss) if max_loss is not None else (1.0e-2 if not acc_enabled else None)
        if loss is not None and loss_lim is not None and float(loss) > float(loss_lim):
            reasons.append(f"constrain_loss={float(loss):.4g}>{float(loss_lim):.4g}")
        if (
            max_span is not None
            and psi_span is not None
            and float(psi_span) > float(max_span)
        ):
            reasons.append(f"xpt_psi_span={float(psi_span):.4g}>{float(max_span):.4g}")

        if reasons:
            shape_status = "gs_converged_shape_unverified"
        else:
            shape_status = "shape_accepted" if acc_enabled else "shape_plausible"

    shape_accepted = shape_status in {"shape_accepted", "shape_plausible"}

    return {
        "null_topology": topology,
        "dn_claimed": bool(dn_claimed),
        "dn_x_count_ok": bool(dn_x_ok),
        "constrain_loss_final": loss,
        "critical": crit,
        "targets": target_scores,
        "xpt_psi_span": psi_span,
        "shape_status": shape_status,
        "shape_accepted": bool(shape_accepted),
        "acceptance_enabled": bool(acc_enabled),
        "acceptance_on_fail": on_fail,
        "fail_reasons": reasons,
        "acceptance": acc if acc_enabled else None,
        "notes": [
            "FreeGSNKE Inverse stop condition is GS residual / relative ψ update; "
            "constraint loss is not a FreeGSNKE stop gate (example01a-class).",
            "Critical points scored on total ψ (eq.psi), not plasma_psi alone.",
            (
                "Shape acceptance uses declared solver.inverse_shape_acceptance thresholds."
                if acc_enabled
                else "Shape acceptance authority disabled; soft honesty labels only."
            ),
        ],
    }


def apply_acceptance_status(
    *,
    gs_ok: bool,
    gs_status: str,
    audit: Mapping[str, Any],
) -> Dict[str, Any]:
    """Merge GS result with shape audit into honest status / ok flag."""
    if not gs_ok:
        return {
            "ok": False,
            "status": str(gs_status or "not_converged"),
            "shape_accepted": False,
        }
    shape_ok = bool(audit.get("shape_accepted"))
    status = str(audit.get("shape_status") or "gs_converged_shape_unverified")
    on_fail = str(audit.get("acceptance_on_fail") or "label_only")
    if shape_ok:
        return {"ok": True, "status": "shape_accepted" if audit.get("acceptance_enabled") else "converged", "shape_accepted": True}
    if on_fail == "blocking":
        return {"ok": False, "status": status, "shape_accepted": False}
    if on_fail == "soft_skip_time":
        return {"ok": False, "status": status, "shape_accepted": False, "soft_skip": True}
    # label_only: keep ok=True (GS succeeded) but honest status
    return {"ok": True, "status": status, "shape_accepted": False}


def port_critical_to_eq(eq: Any, profiles: Any, crit: Mapping[str, Any]) -> None:
    """Write O/X onto ``eq`` and ``profiles`` (FreeGSNKE port_critical-style)."""
    opt = crit.get("opt") or []
    xpt = crit.get("xpt") or []
    if opt:
        profiles.opt = opt
        try:
            eq.opt = opt
        except Exception:
            pass
        if crit.get("psi_axis") is not None:
            try:
                profiles.psi_axis = float(crit["psi_axis"])
                eq.psi_axis = float(crit["psi_axis"])
            except Exception:
                pass
    if xpt:
        profiles.xpt = xpt
        try:
            eq.xpt = xpt
        except Exception:
            pass
        if crit.get("psi_bndry") is not None:
            try:
                profiles.psi_bndry = float(crit["psi_bndry"])
                eq.psi_bndry = float(crit["psi_bndry"])
            except Exception:
                pass
    try:
        eq._profiles = profiles
    except Exception:
        pass
