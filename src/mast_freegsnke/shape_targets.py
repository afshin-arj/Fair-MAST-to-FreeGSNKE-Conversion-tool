"""ADR-004 Path B1: declared EFIT++ shape targets for GSPulse-style isoflux (no invent).

Builds knot-wise shape scalars + LCFS control points from FAIR-MAST Level-2
``equilibrium`` (archived EFIT++). Soft-skips when archive is insufficient unless
``require=true``. Never fabricates geometry.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np


class ShapeTargetsError(ValueError):
    pass


def _strict_bool(value: Any, name: str, *, default: Optional[bool] = None) -> bool:
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise ShapeTargetsError(f"{name} must be a JSON boolean (got {type(value).__name__})")
    return value


ALLOWED_KNOT = frozenset({"linspace_window_inclusive", "window_midpoint"})
ALLOWED_CP = frozenset({"subsample_lcfs_evenly", "none"})


@dataclass(frozen=True)
class ShapeTargetsAuthority:
    authority_name: str = "shape_targets"
    authority_version: str = "1.0.0"
    enabled: bool = True
    require: bool = False
    source: str = "fairmast_level2_equilibrium"
    equilibrium_group: str = "equilibrium"
    knot_policy: str = "linspace_window_inclusive"
    n_knots: int = 21
    shape_scalars: Tuple[str, ...] = (
        "elongation",
        "magnetic_axis_r",
        "magnetic_axis_z",
        "x_point_r",
        "x_point_z",
        "wmhd",
    )
    lcfs_vars: Tuple[str, ...] = ("lcfs_r", "lcfs_z")
    n_control_points: int = 32
    control_point_policy: str = "subsample_lcfs_evenly"
    tokamark_aligned: bool = True
    notes: str = ""

    def validate(self) -> None:
        if not self.authority_name.strip():
            raise ShapeTargetsError("authority_name required")
        if self.source != "fairmast_level2_equilibrium":
            raise ShapeTargetsError(
                "source must be fairmast_level2_equilibrium (v1; never invent geometry)"
            )
        if self.equilibrium_group != "equilibrium":
            raise ShapeTargetsError("equilibrium_group must be 'equilibrium'")
        if self.knot_policy not in ALLOWED_KNOT:
            raise ShapeTargetsError(f"knot_policy must be one of {sorted(ALLOWED_KNOT)}")
        if not (2 <= int(self.n_knots) <= 500):
            raise ShapeTargetsError("n_knots must be in [2, 500]")
        if self.control_point_policy not in ALLOWED_CP:
            raise ShapeTargetsError(
                f"control_point_policy must be one of {sorted(ALLOWED_CP)}"
            )
        if not (0 <= int(self.n_control_points) <= 512):
            raise ShapeTargetsError("n_control_points must be in [0, 512]")
        if not self.shape_scalars and self.control_point_policy == "none":
            raise ShapeTargetsError("shape_scalars empty and control_point_policy=none — nothing to extract")

    def to_json_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["shape_scalars"] = list(self.shape_scalars)
        d["lcfs_vars"] = list(self.lcfs_vars)
        return d


def load_shape_targets_authority(path: Path) -> ShapeTargetsAuthority:
    path = Path(path)
    if not path.exists():
        raise ShapeTargetsError(f"shape_targets_authority not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ShapeTargetsError("shape_targets_authority must be a JSON object")
    auth = ShapeTargetsAuthority(
        authority_name=str(obj.get("authority_name", "shape_targets")),
        authority_version=str(obj.get("authority_version", "1.0.0")),
        enabled=_strict_bool(obj.get("enabled"), "enabled", default=True),
        require=_strict_bool(obj.get("require"), "require", default=False),
        source=str(obj.get("source", "fairmast_level2_equilibrium")),
        equilibrium_group=str(obj.get("equilibrium_group", "equilibrium")),
        knot_policy=str(obj.get("knot_policy", "linspace_window_inclusive")),
        n_knots=int(obj.get("n_knots", 21)),
        shape_scalars=tuple(
            str(x)
            for x in (
                obj.get("shape_scalars")
                or ShapeTargetsAuthority().shape_scalars
            )
        ),
        lcfs_vars=tuple(str(x) for x in (obj.get("lcfs_vars") or ("lcfs_r", "lcfs_z"))),
        n_control_points=int(obj.get("n_control_points", 32)),
        control_point_policy=str(
            obj.get("control_point_policy", "subsample_lcfs_evenly")
        ),
        tokamark_aligned=_strict_bool(
            obj.get("tokamark_aligned"), "tokamark_aligned", default=True
        ),
        notes=str(obj.get("notes", "")),
    )
    auth.validate()
    return auth


def write_shape_targets_authority(inputs_dir: Path, auth: ShapeTargetsAuthority) -> Path:
    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "shape_targets_authority"
    root.mkdir(parents=True, exist_ok=True)
    auth.validate()
    path = root / "shape_targets_authority.json"
    path.write_text(json.dumps(auth.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def _subsample_lcfs(
    r: np.ndarray, z: np.ndarray, n_points: int
) -> Optional[Dict[str, List[float]]]:
    rr = np.asarray(r, dtype=float).ravel()
    zz = np.asarray(z, dtype=float).ravel()
    m = np.isfinite(rr) & np.isfinite(zz)
    rr, zz = rr[m], zz[m]
    if rr.size < 3 or n_points <= 0:
        return None
    if rr.size <= n_points:
        idx = np.arange(rr.size)
    else:
        idx = np.linspace(0, rr.size - 1, n_points).astype(int)
    return {
        "r_m": [float(rr[i]) for i in idx],
        "z_m": [float(zz[i]) for i in idx],
        "n": int(len(idx)),
        "policy": "subsample_lcfs_evenly",
        "source_n": int(rr.size),
    }


def build_shape_targets_from_equilibrium(
    *,
    cache_dir: Path,
    auth: ShapeTargetsAuthority,
    t_start: float,
    t_end: float,
    n_knots_override: Optional[int] = None,
) -> Dict[str, Any]:
    """Extract knot-wise shape scalars + LCFS control points. Never invents missing fields."""
    from .efit_compare import (
        _extract_lcfs_at,
        _nearest_index,
        _open_equilibrium,
        _series_1d,
        _time_coord,
        EfitCompareError,
    )

    auth.validate()
    if not auth.enabled:
        return {
            "status": "disabled",
            "present": False,
            "knots": [],
            "note": "shape_targets_authority.enabled=false",
        }

    n_k = int(n_knots_override) if n_knots_override is not None else int(auth.n_knots)
    if auth.knot_policy == "window_midpoint":
        times_q = np.asarray([0.5 * (float(t_start) + float(t_end))], dtype=float)
    else:
        if float(t_end) <= float(t_start):
            raise ShapeTargetsError("require t_end > t_start for shape targets")
        times_q = np.linspace(float(t_start), float(t_end), n_k)

    try:
        ds = _open_equilibrium(Path(cache_dir), auth.equilibrium_group)
    except FileNotFoundError as e:
        return {
            "status": "skipped_insufficient_archive",
            "present": False,
            "knots": [],
            "error": str(e),
            "note": "equilibrium.zarr missing — download optional group or soft-skip",
        }
    except EfitCompareError as e:
        return {
            "status": "skipped_insufficient_archive",
            "present": False,
            "knots": [],
            "error": str(e),
        }

    try:
        t_src = _time_coord(ds)
        available = sorted(str(v) for v in ds.data_vars)
        series: Dict[str, Optional[np.ndarray]] = {}
        found_scalars: List[str] = []
        missing_scalars: List[str] = []
        for name in auth.shape_scalars:
            s = _series_1d(ds, name)
            series[name] = s
            if s is None:
                missing_scalars.append(name)
            else:
                found_scalars.append(name)

        r_name, z_name = (auth.lcfs_vars + ("lcfs_r", "lcfs_z"))[:2]
        knots: List[Dict[str, Any]] = []
        n_with_lcfs = 0
        for tq in times_q:
            idx = _nearest_index(t_src, float(tq))
            scalars: Dict[str, Any] = {}
            for name in found_scalars:
                arr = series[name]
                assert arr is not None
                if idx < arr.size and np.isfinite(arr[idx]):
                    scalars[name] = float(arr[idx])
                else:
                    scalars[name] = None
            cp = None
            if auth.control_point_policy == "subsample_lcfs_evenly" and auth.n_control_points > 0:
                lcfs = _extract_lcfs_at(ds, idx, r_name, z_name)
                if lcfs is not None:
                    cp = _subsample_lcfs(lcfs[0], lcfs[1], int(auth.n_control_points))
                    if cp is not None:
                        n_with_lcfs += 1
            knots.append(
                {
                    "t_s": float(tq),
                    "t_archive_s": float(t_src[idx]) if idx < t_src.size else None,
                    "archive_index": int(idx),
                    "scalars": scalars,
                    "control_points": cp,
                }
            )
    finally:
        try:
            ds.close()
        except Exception:
            pass

    present = bool(found_scalars) or n_with_lcfs > 0
    if not present:
        status = "skipped_insufficient_archive"
        note = (
            "No declared shape_scalars or LCFS found in equilibrium archive "
            f"(available_vars sample={available[:20]})"
        )
    else:
        status = "ok"
        note = (
            f"Extracted {len(found_scalars)} scalar families, "
            f"LCFS control points at {n_with_lcfs}/{len(knots)} knots; "
            "isoflux QP consumption deferred to Path B2"
        )

    return {
        "status": status,
        "present": present,
        "source": auth.source,
        "equilibrium_group": auth.equilibrium_group,
        "authority_version": auth.authority_version,
        "tokamark_aligned": auth.tokamark_aligned,
        "t_start": float(t_start),
        "t_end": float(t_end),
        "n_knots": len(knots),
        "knot_policy": auth.knot_policy,
        "found_scalars": found_scalars,
        "missing_scalars": missing_scalars,
        "n_knots_with_lcfs_control_points": n_with_lcfs,
        "available_vars": available,
        "knots": knots,
        "picard_ready": False,
        "isoflux_cost_wired": False,
        "note": note,
        "notes_authority": auth.notes,
    }


def run_shape_targets_stage(
    *,
    run_dir: Path,
    inputs_dir: Path,
    cache_dir: Path,
    auth: ShapeTargetsAuthority,
    t_start: float,
    t_end: float,
    n_knots_override: Optional[int] = None,
    planner_out_relpath: str = "07_planner",
) -> Dict[str, Any]:
    """Snapshot authority + shape_targets.json under inputs/; copy summary to 07_planner/."""
    run_dir = Path(run_dir)
    inputs_dir = Path(inputs_dir)
    write_shape_targets_authority(inputs_dir, auth)
    payload = build_shape_targets_from_equilibrium(
        cache_dir=Path(cache_dir),
        auth=auth,
        t_start=t_start,
        t_end=t_end,
        n_knots_override=n_knots_override,
    )

    root = inputs_dir / "shape_targets_authority"
    root.mkdir(parents=True, exist_ok=True)
    data_path = root / "shape_targets.json"
    data_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    planner_dir = run_dir / planner_out_relpath
    planner_dir.mkdir(parents=True, exist_ok=True)
    (planner_dir / "shape_targets.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    if auth.require and payload.get("status") != "ok":
        raise ShapeTargetsError(
            f"shape_targets require=true but status={payload.get('status')!r}: "
            f"{payload.get('note') or payload.get('error')}"
        )

    return {
        "ok": payload.get("status") in {"ok", "disabled"}
        or (not auth.require and payload.get("status") == "skipped_insufficient_archive"),
        "status": payload.get("status"),
        "present": bool(payload.get("present")),
        "path": str(data_path),
        "planner_copy": str(planner_dir / "shape_targets.json"),
        "payload": payload,
    }
