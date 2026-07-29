"""Remap Inverse BoundarySpec from FAIR-MAST EFIT++ shape_targets (ADR-004 Path B1).

Puts archived divertor tip(s) on the same isoflux surface as LCFS control
points so FreeGSNKE's separatrix is constrained through SN one X or DN both
tips. Never invents X/LCFS — soft-skips when shape_targets are missing/incomplete.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .execution_authority import BoundarySpec, load_execution_authority_bundle


def _finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def load_shape_targets_obj(inputs_dir: Path) -> Optional[Dict[str, Any]]:
    path = Path(inputs_dir) / "shape_targets_authority" / "shape_targets.json"
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def pick_shape_knot(
    shape_targets: Dict[str, Any], *, t_s: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    knots = shape_targets.get("knots")
    if not isinstance(knots, list) or not knots:
        return None
    usable = [k for k in knots if isinstance(k, dict)]
    if not usable:
        return None
    if t_s is None:
        return usable[len(usable) // 2]
    return min(
        usable,
        key=lambda k: abs(float(k.get("t_s", k.get("t_archive_s", 0.0))) - float(t_s)),
    )


def _lcfs_divertor_tips(
    r_cp: Sequence[float],
    z_cp: Sequence[float],
    *,
    archive_xr: float,
    archive_xz: float,
    r_near_frac: float = 0.35,
    z_min_abs: float = 0.35,
) -> Dict[str, Any]:
    """Pick upper/lower divertor tips from archive LCFS (never invents points).

    Tips are extreme-|Z| LCFS samples whose R is near the archive divertor X.
    Topology: single_null if only one hemisphere tip is usable; double_null if both.
    """
    r = np.asarray(r_cp, dtype=float).ravel()
    z = np.asarray(z_cp, dtype=float).ravel()
    out: Dict[str, Any] = {
        "lower": None,
        "upper": None,
        "null_topology": "single_null",
        "tips": [],
    }
    if r.size < 3 or r.size != z.size:
        out["tips"] = [{"r": float(archive_xr), "z": float(archive_xz), "source": "shape_targets_x"}]
        return out

    r_span = float(np.nanmax(r) - np.nanmin(r))
    dr = max(0.08, float(r_near_frac) * r_span) if np.isfinite(r_span) else 0.25
    near = np.isfinite(r) & np.isfinite(z) & (np.abs(r - float(archive_xr)) <= dr)

    def _tip(mask: np.ndarray, *, prefer_min_z: bool) -> Optional[Dict[str, float]]:
        if not np.any(mask):
            return None
        zz = z[mask]
        rr = r[mask]
        # Require a real divertor-like |Z| (not midplane noise)
        if float(np.nanmax(np.abs(zz))) < float(z_min_abs):
            return None
        i = int(np.nanargmin(zz) if prefer_min_z else np.nanargmax(zz))
        return {
            "r": float(rr[i]),
            "z": float(zz[i]),
            "source": "lcfs_extremum",
        }

    lower = _tip(near & (z < 0.0), prefer_min_z=True)
    upper = _tip(near & (z > 0.0), prefer_min_z=False)

    # Always keep the cited archive X as a tip (exact EFIT scalar).
    archive_tip = {
        "r": float(archive_xr),
        "z": float(archive_xz),
        "source": "shape_targets_x",
    }
    if float(archive_xz) <= 0.0:
        if lower is None or abs(float(archive_xz)) >= abs(float(lower["z"])) - 1e-9:
            lower = archive_tip
    else:
        if upper is None or abs(float(archive_xz)) >= abs(float(upper["z"])) - 1e-9:
            upper = archive_tip

    out["lower"] = lower
    out["upper"] = upper
    tips: List[Dict[str, Any]] = []
    if lower is not None:
        tips.append(dict(lower, hemisphere="lower"))
    if upper is not None:
        tips.append(dict(upper, hemisphere="upper"))
    if not tips:
        tips = [dict(archive_tip, hemisphere="archive")]
    out["tips"] = tips
    out["null_topology"] = "double_null" if (lower is not None and upper is not None) else "single_null"
    return out


def _prepend_isoflux_points(
    r_cp: List[float],
    z_cp: List[float],
    tips: Sequence[Mapping[str, Any]],
    *,
    dedupe_tol: float = 1e-3,
) -> Tuple[List[float], List[float]]:
    """Move divertor tips to the front of isoflux control points (dedupe)."""
    r_out = list(r_cp)
    z_out = list(z_cp)
    for tip in reversed(list(tips)):
        tr = _finite(tip.get("r"))
        tz = _finite(tip.get("z"))
        if tr is None or tz is None:
            continue
        # Drop any near-duplicate already in the list, then prepend tip.
        keep_r: List[float] = []
        keep_z: List[float] = []
        for rr, zz in zip(r_out, z_out):
            if abs(float(rr) - tr) <= dedupe_tol and abs(float(zz) - tz) <= dedupe_tol:
                continue
            keep_r.append(float(rr))
            keep_z.append(float(zz))
        r_out = [tr] + keep_r
        z_out = [tz] + keep_z
    return r_out, z_out


def boundary_from_shape_knot(
    knot: Dict[str, Any],
    *,
    fallback: BoundarySpec,
) -> Tuple[Optional[BoundarySpec], Dict[str, Any]]:
    """Build BoundarySpec: archive X (+ axis O) nulls + LCFS isoflux including divertor tips.

    Returns ``(spec_or_None, provenance)``.
    """
    prov: Dict[str, Any] = {
        "source": "shape_targets",
        "t_s": knot.get("t_s"),
        "t_archive_s": knot.get("t_archive_s"),
        "ok": False,
    }
    scalars = knot.get("scalars") if isinstance(knot.get("scalars"), dict) else {}
    xr = _finite(scalars.get("x_point_r"))
    xz = _finite(scalars.get("x_point_z"))
    if xr is None or xz is None:
        prov["error"] = "missing_archive_x_point"
        return None, prov

    ar = _finite(scalars.get("magnetic_axis_r"))
    az = _finite(scalars.get("magnetic_axis_z"))
    if ar is None or az is None:
        # Keep template O-point rather than invent axis
        try:
            ar = float(fallback.null_points[0][1])
            az = float(fallback.null_points[1][1])
            prov["o_point_source"] = "execution_authority_fallback"
        except Exception:
            prov["error"] = "missing_magnetic_axis_and_fallback"
            return None, prov
    else:
        prov["o_point_source"] = "shape_targets"

    cp = knot.get("control_points")
    r_cp: List[float] = []
    z_cp: List[float] = []
    if isinstance(cp, dict):
        # FAIR-MAST / shape_targets use r_m/z_m; also accept R_m/R/r variants.
        rr = (
            cp.get("r_m")
            or cp.get("R_m")
            or cp.get("R")
            or cp.get("r")
        )
        zz = (
            cp.get("z_m")
            or cp.get("Z_m")
            or cp.get("Z")
            or cp.get("z")
        )
        if rr is not None and zz is not None:
            r_arr = np.asarray(rr, dtype=float).ravel()
            z_arr = np.asarray(zz, dtype=float).ravel()
            m = np.isfinite(r_arr) & np.isfinite(z_arr)
            r_cp = [float(v) for v in r_arr[m]]
            z_cp = [float(v) for v in z_arr[m]]

    tip_info = _lcfs_divertor_tips(r_cp, z_cp, archive_xr=float(xr), archive_xz=float(xz))
    tips = list(tip_info.get("tips") or [])
    topology = str(tip_info.get("null_topology") or "single_null")
    prov["null_topology"] = topology
    prov["divertor_tips"] = tips

    # FreeGSNKE Inverse_optimizer: null_points = [Rcoords, Zcoords]
    # SN: X + O. DN: X_lower + O + X_upper (archive tips only — no invent).
    if topology == "double_null" and tip_info.get("lower") and tip_info.get("upper"):
        lo = tip_info["lower"]
        up = tip_info["upper"]
        null_points = [
            [float(lo["r"]), float(ar), float(up["r"])],
            [float(lo["z"]), float(az), float(up["z"])],
        ]
        prov["null_points"] = {
            "x_point_lower": [float(lo["r"]), float(lo["z"])],
            "o_point": [float(ar), float(az)],
            "x_point_upper": [float(up["r"]), float(up["z"])],
            "x_point_primary_archive": [float(xr), float(xz)],
        }
    else:
        null_points = [[float(xr), float(ar)], [float(xz), float(az)]]
        prov["null_points"] = {
            "x_point": [float(xr), float(xz)],
            "o_point": [float(ar), float(az)],
        }

    if len(r_cp) < 3:
        # Keep template isoflux geometry but force divertor tips through ψ
        try:
            iso0 = fallback.isoflux_set[0]
            r_legacy = [float(v) for v in iso0[0]]
            z_legacy = [float(v) for v in iso0[1]]
            if len(r_legacy) >= 2 and len(z_legacy) >= 2:
                r_cp, z_cp = _prepend_isoflux_points(r_legacy, z_legacy, tips)
                prov["isoflux_source"] = "execution_authority_isoflux_with_divertor_tips"
            else:
                prov["error"] = "insufficient_lcfs_control_points"
                return None, prov
        except Exception:
            r_cp = [float(t["r"]) for t in tips] + [float(ar)]
            z_cp = [float(t["z"]) for t in tips] + [float(az)]
            prov["isoflux_source"] = "divertor_tips_and_o_minimal"
    else:
        r_cp, z_cp = _prepend_isoflux_points(r_cp, z_cp, tips)
        prov["isoflux_source"] = "lcfs_control_points_with_divertor_tips"

    isoflux_set = [[r_cp, z_cp]]
    spec = BoundarySpec(null_points=null_points, isoflux_set=isoflux_set)
    try:
        spec.validate()
    except Exception as e:
        prov["error"] = f"boundary_validate_failed:{e}"
        return None, prov
    prov["ok"] = True
    prov["n_isoflux_points"] = len(r_cp)
    return spec, prov


def apply_shape_targets_to_execution_boundary(
    inputs_dir: Path,
    *,
    t_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Rewrite execution_authority boundary from shape_targets when possible."""
    from dataclasses import asdict, replace

    inputs_dir = Path(inputs_dir)
    report: Dict[str, Any] = {
        "ok": False,
        "status": "skipped",
        "path": None,
        "errors": [],
        "provenance": {},
    }
    st = load_shape_targets_obj(inputs_dir)
    if st is None:
        report["status"] = "skipped_missing_shape_targets"
        return report
    if str(st.get("status") or "") != "ok":
        report["status"] = f"skipped_shape_targets_status:{st.get('status')}"
        return report

    bundle_path = inputs_dir / "execution_authority" / "execution_authority_bundle.json"
    if not bundle_path.is_file():
        report["status"] = "skipped_missing_execution_authority"
        report["errors"].append("execution_authority_bundle.json missing")
        return report

    try:
        bundle = load_execution_authority_bundle(bundle_path)
    except Exception as e:
        report["status"] = "failed_load_bundle"
        report["errors"].append(str(e))
        return report

    knot = pick_shape_knot(st, t_s=t_s)
    if knot is None:
        report["status"] = "skipped_no_knots"
        return report

    new_bnd, prov = boundary_from_shape_knot(knot, fallback=bundle.boundary)
    report["provenance"] = prov
    if new_bnd is None:
        report["status"] = "skipped_incomplete_shape_knot"
        return report

    new_bundle = replace(bundle, boundary=new_bnd)
    new_bundle.validate()
    root = inputs_dir / "execution_authority"
    (root / "execution_authority_bundle.json").write_text(
        json.dumps(new_bundle.to_json_dict(), indent=2) + "\n", encoding="utf-8"
    )
    (root / "boundary_spec.json").write_text(
        json.dumps(asdict(new_bnd), indent=2) + "\n", encoding="utf-8"
    )
    prov_path = root / "boundary_from_shape_targets.json"
    prov_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    report["ok"] = True
    report["status"] = "ok"
    report["path"] = str(prov_path.as_posix())
    return report


def boundary_dict_at_time(
    inputs_dir: Path,
    *,
    t_s: float,
    fallback: Mapping[str, Any],
) -> Dict[str, Any]:
    """Nearest archive shape_targets knot → Inverse boundary dict (no invent).

    Returns ``fallback`` unchanged when shape_targets are missing/incomplete.
    Preserves optional ``coil_current_limits`` from fallback when present.
    """
    inputs_dir = Path(inputs_dir)
    out = {
        "null_points": fallback.get("null_points"),
        "isoflux_set": fallback.get("isoflux_set"),
    }
    if fallback.get("coil_current_limits") is not None:
        out["coil_current_limits"] = fallback.get("coil_current_limits")

    st = load_shape_targets_obj(inputs_dir)
    if st is None or str(st.get("status") or "") != "ok":
        return out
    knot = pick_shape_knot(st, t_s=float(t_s))
    if knot is None:
        return out
    try:
        fb = BoundarySpec(
            null_points=list(fallback["null_points"]),
            isoflux_set=list(fallback["isoflux_set"]),
            coil_current_limits=fallback.get("coil_current_limits"),
        )
    except Exception:
        return out
    spec, prov = boundary_from_shape_knot(knot, fallback=fb)
    if spec is None or not prov.get("ok"):
        return out
    out = {
        "null_points": spec.null_points,
        "isoflux_set": spec.isoflux_set,
    }
    if spec.coil_current_limits is not None:
        out["coil_current_limits"] = spec.coil_current_limits
    elif fallback.get("coil_current_limits") is not None:
        out["coil_current_limits"] = fallback.get("coil_current_limits")
    return out
