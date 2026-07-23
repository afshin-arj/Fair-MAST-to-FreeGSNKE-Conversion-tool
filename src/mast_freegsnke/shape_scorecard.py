"""Paper-style shape-control scorecard (arXiv:2407.12432 metrics family).

Compares FreeGSNKE vs FAIR-MAST EFIT++ archive quantities when present.
Never invents missing FreeGSNKE or EFIT fields — reports null + note.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def midplane_radii(
    r: np.ndarray,
    z: np.ndarray,
    *,
    z_ref: float = 0.0,
    z_tol: float = 0.05,
) -> Dict[str, Optional[float]]:
    """Inner/outer midplane R from an LCFS polyline near z_ref.

    Matches the spirit of Pentland et al. shape targets (midplane radii).
    """
    r = np.asarray(r, dtype=float).ravel()
    z = np.asarray(z, dtype=float).ravel()
    m = np.isfinite(r) & np.isfinite(z)
    r, z = r[m], z[m]
    if r.size < 3:
        return {"R_in_m": None, "R_out_m": None, "z_ref_m": float(z_ref), "n_points_used": 0}
    near = np.abs(z - float(z_ref)) <= float(z_tol)
    if near.sum() < 2:
        # fallback: take points with smallest |z - z_ref|
        order = np.argsort(np.abs(z - float(z_ref)))
        take = order[: max(4, min(12, r.size))]
        rr = r[take]
    else:
        rr = r[near]
    return {
        "R_in_m": float(np.min(rr)),
        "R_out_m": float(np.max(rr)),
        "z_ref_m": float(z_ref),
        "n_points_used": int(rr.size),
    }


def polyline_mean_nearest_distance_m(
    r_a: np.ndarray,
    z_a: np.ndarray,
    r_b: np.ndarray,
    z_b: np.ndarray,
) -> Dict[str, Optional[float]]:
    """Symmetric mean nearest-neighbour distance between two polylines [m]."""
    a = np.column_stack([np.asarray(r_a, dtype=float).ravel(), np.asarray(z_a, dtype=float).ravel()])
    b = np.column_stack([np.asarray(r_b, dtype=float).ravel(), np.asarray(z_b, dtype=float).ravel()])
    a = a[np.isfinite(a).all(axis=1)]
    b = b[np.isfinite(b).all(axis=1)]
    if a.shape[0] < 3 or b.shape[0] < 3:
        return {
            "mean_nn_A_to_B_m": None,
            "mean_nn_B_to_A_m": None,
            "mean_nn_symmetric_m": None,
            "max_nn_symmetric_m": None,
        }

    def _nn_stats(src: np.ndarray, dst: np.ndarray) -> Tuple[float, float]:
        # chunked to avoid huge allocations
        dmin = np.empty(src.shape[0], dtype=float)
        chunk = 256
        for i0 in range(0, src.shape[0], chunk):
            i1 = min(i0 + chunk, src.shape[0])
            diff = src[i0:i1, None, :] - dst[None, :, :]
            d2 = np.sum(diff * diff, axis=2)
            dmin[i0:i1] = np.sqrt(np.min(d2, axis=1))
        return float(np.mean(dmin)), float(np.max(dmin))

    ab_mean, ab_max = _nn_stats(a, b)
    ba_mean, ba_max = _nn_stats(b, a)
    return {
        "mean_nn_A_to_B_m": ab_mean,
        "mean_nn_B_to_A_m": ba_mean,
        "mean_nn_symmetric_m": 0.5 * (ab_mean + ba_mean),
        "max_nn_symmetric_m": max(ab_max, ba_max),
    }


def _finite(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except Exception:
        return None
    return v if math.isfinite(v) else None


def extract_freegsnke_shape_targets(eq: Any) -> Dict[str, Any]:
    """Best-effort shape targets from a FreeGS/FreeGSNKE equilibrium object."""
    out: Dict[str, Any] = {
        "magnetic_axis_r": None,
        "magnetic_axis_z": None,
        "x_point_r": None,
        "x_point_z": None,
        "R_in_m": None,
        "R_out_m": None,
        "notes": [],
    }
    if eq is None:
        out["notes"].append("no_equilibrium_object")
        return out

    # Magnetic axis
    for r_attr, z_attr in (
        ("Rmin", None),  # placeholder skip
    ):
        pass
    for pair in (
        ("Raxis", "Zaxis"),
        ("magnetic_axis_r", "magnetic_axis_z"),
    ):
        ra, za = getattr(eq, pair[0], None), getattr(eq, pair[1], None)
        if ra is not None and za is not None:
            out["magnetic_axis_r"] = _finite(ra)
            out["magnetic_axis_z"] = _finite(za)
            break
    # FreeGS often stores opt as (R,Z) of O-point
    opt = getattr(eq, "_opt", None) or getattr(eq, "opt", None)
    if out["magnetic_axis_r"] is None and opt is not None:
        try:
            arr = np.asarray(opt, dtype=float).ravel()
            if arr.size >= 2:
                out["magnetic_axis_r"] = _finite(arr[0])
                out["magnetic_axis_z"] = _finite(arr[1])
        except Exception:
            out["notes"].append("opt_parse_failed")

    # X-point(s): take closest to axis if multiple
    xpts = getattr(eq, "x_points", None) or getattr(eq, "xpoints", None)
    if xpts is not None:
        try:
            pts = []
            for xp in xpts:
                if hasattr(xp, "R"):
                    pts.append((float(xp.R), float(xp.Z)))
                else:
                    a = np.asarray(xp, dtype=float).ravel()
                    if a.size >= 2:
                        pts.append((float(a[0]), float(a[1])))
            if pts:
                if out["magnetic_axis_r"] is not None and out["magnetic_axis_z"] is not None:
                    pts = sorted(
                        pts,
                        key=lambda p: (p[0] - out["magnetic_axis_r"]) ** 2
                        + (p[1] - out["magnetic_axis_z"]) ** 2,
                    )
                out["x_point_r"] = _finite(pts[0][0])
                out["x_point_z"] = _finite(pts[0][1])
        except Exception:
            out["notes"].append("xpoint_parse_failed")

    # Midplane from boundary
    r = getattr(eq, "rboundary", None) or getattr(eq, "Rbound", None)
    z = getattr(eq, "zboundary", None) or getattr(eq, "Zbound", None)
    if r is not None and z is not None:
        z_ref = out["magnetic_axis_z"] if out["magnetic_axis_z"] is not None else 0.0
        mid = midplane_radii(np.asarray(r), np.asarray(z), z_ref=float(z_ref))
        out["R_in_m"] = mid["R_in_m"]
        out["R_out_m"] = mid["R_out_m"]
        out["midplane"] = mid
    else:
        out["notes"].append("no_boundary_for_midplane")
    return out


def build_shape_scorecard(
    *,
    efit_scalars: Dict[str, Any],
    efit_lcfs: Optional[Tuple[np.ndarray, np.ndarray]],
    freegsnke_lcfs: Optional[Tuple[np.ndarray, np.ndarray]],
    freegsnke_shape: Optional[Dict[str, Any]],
    psi_convention: str,
    compare_mode: str,
    validation_reference: str,
) -> Dict[str, Any]:
    """Assemble arXiv:2407.12432-style shape scorecard (reconstruction vs archive)."""
    rows: List[Dict[str, Any]] = []

    def _row(name: str, efit_v: Any, fg_v: Any, unit: str = "") -> None:
        ev = _finite(efit_v)
        fv = _finite(fg_v)
        delta = None if (ev is None or fv is None) else float(fv - ev)
        rows.append(
            {
                "quantity": name,
                "unit": unit,
                "efit_archive": ev,
                "freegsnke": fv,
                "delta_freegsnke_minus_efit": delta,
                "available": ev is not None or fv is not None,
            }
        )

    fg = freegsnke_shape or {}
    _row("magnetic_axis_r", efit_scalars.get("magnetic_axis_r"), fg.get("magnetic_axis_r"), "m")
    _row("magnetic_axis_z", efit_scalars.get("magnetic_axis_z"), fg.get("magnetic_axis_z"), "m")
    _row("x_point_r", efit_scalars.get("x_point_r"), fg.get("x_point_r"), "m")
    _row("x_point_z", efit_scalars.get("x_point_z"), fg.get("x_point_z"), "m")
    _row("elongation", efit_scalars.get("elongation"), None, "")
    _row("minor_radius", efit_scalars.get("minor_radius"), None, "m")
    _row("q95", efit_scalars.get("q95"), None, "")

    efit_mid = None
    if efit_lcfs is not None:
        z_ref = _finite(efit_scalars.get("magnetic_axis_z")) or 0.0
        efit_mid = midplane_radii(efit_lcfs[0], efit_lcfs[1], z_ref=z_ref)
        _row("R_in_midplane", efit_mid.get("R_in_m"), fg.get("R_in_m"), "m")
        _row("R_out_midplane", efit_mid.get("R_out_m"), fg.get("R_out_m"), "m")
    else:
        _row("R_in_midplane", None, fg.get("R_in_m"), "m")
        _row("R_out_midplane", None, fg.get("R_out_m"), "m")

    lcfs_metrics: Dict[str, Any] = {}
    if efit_lcfs is not None and freegsnke_lcfs is not None:
        lcfs_metrics = polyline_mean_nearest_distance_m(
            efit_lcfs[0], efit_lcfs[1], freegsnke_lcfs[0], freegsnke_lcfs[1]
        )
        _row(
            "lcfs_mean_nn_symmetric",
            None,
            lcfs_metrics.get("mean_nn_symmetric_m"),
            "m",
        )
        # put the metric only under freegsnke column as the distance itself
        rows[-1]["efit_archive"] = None
        rows[-1]["delta_freegsnke_minus_efit"] = None
        rows[-1]["note"] = "symmetric mean nearest-neighbour LCFS distance"

    return {
        "compare_mode": compare_mode,
        "compare_mode_note": (
            "reconstruction_vs_archive: FreeGSNKE inverse/forward from FAIR-MAST magnetics "
            "vs archived EFIT++ shapes. This is NOT the Pentland et al. forward-replay setup "
            "(EFIT++ currents+profiles → FreeGSNKE forward)."
            if compare_mode == "reconstruction_vs_archive"
            else str(compare_mode)
        ),
        "psi_convention": psi_convention,
        "psi_convention_note": (
            "FreeGSNKE and EFIT++ use poloidal flux in Wb/2π (Pentland et al. arXiv:2407.12432). "
            "Do not mix with codes that report ψ in Wb without the 2π factor."
        ),
        "validation_reference": validation_reference,
        "efit_midplane": efit_mid,
        "lcfs_distance": lcfs_metrics,
        "rows": rows,
        "n_rows_with_both": sum(
            1
            for r in rows
            if r.get("efit_archive") is not None and r.get("freegsnke") is not None
        ),
    }
