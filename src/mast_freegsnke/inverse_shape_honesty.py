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
) -> Dict[str, Any]:
    """Score solved critical points vs declared Inverse null targets.

    Returns an audit dict. Does not invent tolerances as pass/fail gates unless
    topology claims DN (then ``dn_x_count_ok`` requires ≥2 X on total ψ).
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
    dn_x_ok = (not dn_claimed) or int(crit.get("n_xpt") or 0) >= 2

    loss = _finite(constrain_loss_final)
    # Soft honesty label — GS may be OK while shape is unverified.
    if not crit.get("ok"):
        shape_status = "critical_unavailable"
    elif dn_claimed and not dn_x_ok:
        shape_status = "dn_missing_xpoints"
    elif loss is not None and loss > 1.0e-2:
        shape_status = "gs_converged_shape_unverified"
    elif any(
        (s.get("nearest_solved_dist_m") is not None and float(s["nearest_solved_dist_m"]) > 0.08)
        for s in target_scores
        if s.get("role") == "x"
    ):
        shape_status = "gs_converged_shape_unverified"
    else:
        shape_status = "shape_plausible"

    return {
        "null_topology": topology,
        "dn_claimed": bool(dn_claimed),
        "dn_x_count_ok": bool(dn_x_ok),
        "constrain_loss_final": loss,
        "critical": crit,
        "targets": target_scores,
        "xpt_psi_span": psi_span,
        "shape_status": shape_status,
        "notes": [
            "FreeGSNKE Inverse stop condition is GS residual / relative ψ update; "
            "constraint loss is not a stop gate (example01a-class).",
            "Critical points scored on total ψ (eq.psi), not plasma_psi alone.",
        ],
    }


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
