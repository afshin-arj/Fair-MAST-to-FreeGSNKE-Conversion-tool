"""Remap Inverse BoundarySpec from FAIR-MAST EFIT++ shape_targets (ADR-004 Path B1).

Puts the archived divertor X-point on the same isoflux surface as LCFS control
points so FreeGSNKE's separatrix is constrained to pass through that X.
Never invents X/LCFS — soft-skips when shape_targets are missing/incomplete.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


def boundary_from_shape_knot(
    knot: Dict[str, Any],
    *,
    fallback: BoundarySpec,
) -> Tuple[Optional[BoundarySpec], Dict[str, Any]]:
    """Build BoundarySpec: archive X (+ axis O) nulls + LCFS isoflux including X.

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

    # FreeGSNKE Inverse_optimizer: null_points = [Rcoords, Zcoords]
    null_points = [[float(xr), float(ar)], [float(xz), float(az)]]
    prov["null_points"] = {
        "x_point": [float(xr), float(xz)],
        "o_point": [float(ar), float(az)],
    }

    cp = knot.get("control_points")
    r_cp: List[float] = []
    z_cp: List[float] = []
    if isinstance(cp, dict):
        rr = cp.get("R_m") or cp.get("R") or cp.get("r")
        zz = cp.get("Z_m") or cp.get("Z") or cp.get("z")
        if rr is not None and zz is not None:
            r_arr = np.asarray(rr, dtype=float).ravel()
            z_arr = np.asarray(zz, dtype=float).ravel()
            m = np.isfinite(r_arr) & np.isfinite(z_arr)
            r_cp = [float(v) for v in r_arr[m]]
            z_cp = [float(v) for v in z_arr[m]]
    if len(r_cp) < 3:
        # Keep template isoflux geometry but replace its first point with archive X
        try:
            iso0 = fallback.isoflux_set[0]
            r_legacy = [float(v) for v in iso0[0]]
            z_legacy = [float(v) for v in iso0[1]]
            if len(r_legacy) >= 2 and len(z_legacy) >= 2:
                r_legacy[0] = float(xr)
                z_legacy[0] = float(xz)
                r_cp, z_cp = r_legacy, z_legacy
                prov["isoflux_source"] = "execution_authority_isoflux_with_archive_x"
            else:
                prov["error"] = "insufficient_lcfs_control_points"
                return None, prov
        except Exception:
            # Minimal isoflux: X + a few points near O radius (still needs >=2 pts)
            r_cp = [float(xr), float(ar)]
            z_cp = [float(xz), float(az)]
            prov["isoflux_source"] = "x_and_o_only_minimal"
    else:
        # Prepend archive X so isoflux ψ is forced through the divertor null
        r_cp = [float(xr)] + r_cp
        z_cp = [float(xz)] + z_cp
        prov["isoflux_source"] = "lcfs_control_points_with_archive_x"

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
