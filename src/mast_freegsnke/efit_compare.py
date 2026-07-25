"""ADR-002: compare FreeGSNKE reconstruction to FAIR-MAST EFIT++ equilibrium archive.

Windows-friendly: reads Level-2 ``equilibrium`` Zarr (EFIT++ products), never runs efit-ai Fortran.
Honest labels only — FreeGSNKE vs FAIR-MAST EFIT++ archive.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _HAS_MPL = True
except Exception:  # pragma: no cover
    _HAS_MPL = False

try:
    import xarray as xr

    _HAS_XR = True
except Exception:  # pragma: no cover
    xr = None  # type: ignore
    _HAS_XR = False


class EfitCompareError(ValueError):
    pass


@dataclass(frozen=True)
class EfitCompareAuthority:
    authority_name: str = "efit_compare"
    authority_version: str = "1.1"
    source: str = "fairmast_level2_equilibrium"
    label: str = "FAIR-MAST EFIT++ archive (not efit-ai Fortran)"
    tokamark_reference: str = "https://github.com/UKAEA-IBM-STFC-Fusion-FMs/tokamark"
    fairmast_docs: str = "https://mastapp.site/level2-data.html"
    validation_reference: str = "https://arxiv.org/html/2407.12432v4"
    compare_mode: str = "reconstruction_vs_archive"
    psi_convention: str = "Wb_per_2pi"
    equilibrium_group: str = "equilibrium"
    output_relpath: str = "04_efit_compare"
    fail_closed_if_missing: bool = False
    shape_scalars: Tuple[str, ...] = (
        "elongation",
        "elongation_axis",
        "triangularity_upper",
        "triangularity_lower",
        "minor_radius",
        "magnetic_axis_r",
        "magnetic_axis_z",
        "x_point_r",
        "x_point_z",
        "q95",
        "beta_tor",
        "beta_pol",
        "beta_normal",
        "li",
        "wmhd",
    )
    lcfs_vars: Tuple[str, ...] = ("lcfs_r", "lcfs_z")
    psi_var: str = "psi"
    time_policy: str = "nearest_to_window_midpoint"
    write_side_by_side_gif: bool = True
    side_by_side_n_frames: int = 16
    side_by_side_fps: float = 2.0
    notes: str = (
        "ADR-002/v11.11. Shape scorecard metrics follow Pentland et al. arXiv:2407.12432 "
        "(axis, midplane R, X-point, LCFS distance). Mode is reconstruction_vs_archive, "
        "not EFIT++→FreeGSNKE forward replay. Optional FreeGSNKE|EFIT++ side-by-side GIF "
        "mirrors FreeGSNKE README MAST-U demo for classic MAST archive products."
    )

    def validate(self) -> None:
        if self.source != "fairmast_level2_equilibrium":
            raise EfitCompareError(
                f"unsupported source {self.source!r} "
                "(v1 only fairmast_level2_equilibrium; efit-ai Fortran is out of scope)"
            )
        if self.equilibrium_group != "equilibrium":
            raise EfitCompareError(
                f"equilibrium_group must be 'equilibrium' (got {self.equilibrium_group!r})"
            )
        if self.time_policy != "nearest_to_window_midpoint":
            raise EfitCompareError(
                f"unsupported time_policy {self.time_policy!r} "
                "(v1: nearest_to_window_midpoint)"
            )
        if self.compare_mode != "reconstruction_vs_archive":
            raise EfitCompareError(
                f"unsupported compare_mode {self.compare_mode!r} "
                "(v1.1: reconstruction_vs_archive only; forward_replay needs EFIT profile "
                "coeff authority — out of scope until cited)"
            )
        if self.psi_convention != "Wb_per_2pi":
            raise EfitCompareError(
                f"unsupported psi_convention {self.psi_convention!r} "
                "(declare Wb_per_2pi per FreeGSNKE/EFIT++ / arXiv:2407.12432)"
            )
        if not str(self.output_relpath).strip():
            raise EfitCompareError("output_relpath required")
        if not self.shape_scalars:
            raise EfitCompareError("shape_scalars must be non-empty (declare which EFIT fields to export)")
        if not str(self.validation_reference).strip():
            raise EfitCompareError("validation_reference required (cite arXiv:2407.12432 or successor)")

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["shape_scalars"] = list(self.shape_scalars)
        d["lcfs_vars"] = list(self.lcfs_vars)
        return d


def load_efit_compare_authority(path: Path) -> EfitCompareAuthority:
    if not path.exists():
        raise EfitCompareError(f"missing efit compare authority: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise EfitCompareError("authority root must be an object")
    auth = EfitCompareAuthority(
        authority_name=str(obj.get("authority_name", "efit_compare")),
        authority_version=str(obj.get("authority_version", "1.1")),
        source=str(obj.get("source", "fairmast_level2_equilibrium")),
        label=str(obj.get("label", "FAIR-MAST EFIT++ archive (not efit-ai Fortran)")),
        tokamark_reference=str(
            obj.get(
                "tokamark_reference",
                "https://github.com/UKAEA-IBM-STFC-Fusion-FMs/tokamark",
            )
        ),
        fairmast_docs=str(obj.get("fairmast_docs", "https://mastapp.site/level2-data.html")),
        validation_reference=str(
            obj.get("validation_reference", "https://arxiv.org/html/2407.12432v4")
        ),
        compare_mode=str(obj.get("compare_mode", "reconstruction_vs_archive")),
        psi_convention=str(obj.get("psi_convention", "Wb_per_2pi")),
        equilibrium_group=str(obj.get("equilibrium_group", "equilibrium")),
        output_relpath=str(obj.get("output_relpath", "04_efit_compare")),
        fail_closed_if_missing=bool(obj.get("fail_closed_if_missing", False)),
        shape_scalars=tuple(obj.get("shape_scalars") or EfitCompareAuthority().shape_scalars),
        lcfs_vars=tuple(obj.get("lcfs_vars") or ("lcfs_r", "lcfs_z")),
        psi_var=str(obj.get("psi_var", "psi")),
        time_policy=str(obj.get("time_policy", "nearest_to_window_midpoint")),
        write_side_by_side_gif=bool(obj.get("write_side_by_side_gif", True)),
        side_by_side_n_frames=int(obj.get("side_by_side_n_frames", 16) or 16),
        side_by_side_fps=float(obj.get("side_by_side_fps", 2.0) or 2.0),
        notes=str(obj.get("notes", EfitCompareAuthority().notes)),
    )
    auth.validate()
    return auth


def write_efit_compare_authority(inputs_dir: Path, auth: EfitCompareAuthority) -> Path:
    auth.validate()
    out_dir = Path(inputs_dir) / "efit_compare_authority"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "efit_compare_authority.json"
    path.write_text(json.dumps(auth.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


@dataclass
class EfitCompareReport:
    ok: bool = False
    output_dir: str = ""
    label: str = ""
    compare_mode: str = "reconstruction_vs_archive"
    psi_convention: str = "Wb_per_2pi"
    equilibrium_path: str = ""
    t_query: Optional[float] = None
    t_efit: Optional[float] = None
    t_freegsnke: Optional[float] = None
    time_align_note: str = ""
    files_written: List[str] = field(default_factory=list)
    plots_written: List[str] = field(default_factory=list)
    available_vars: List[str] = field(default_factory=list)
    missing_vars: List[str] = field(default_factory=list)
    freegsnke_boundary_available: bool = False
    shape_scorecard: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    fix_hint: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _load_window_mid(run_dir: Path) -> Optional[float]:
    for rel in ("inputs/window.json", "01_summary/SUMMARY.json"):
        p = Path(run_dir) / rel
        if not p.exists():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if "t_start" in obj and "t_end" in obj:
            return 0.5 * (float(obj["t_start"]) + float(obj["t_end"]))
        w = obj.get("window") or {}
        if "t_start" in w and "t_end" in w:
            return 0.5 * (float(w["t_start"]) + float(w["t_end"]))
    return None


def _open_equilibrium(cache_dir: Path, group: str = "equilibrium") -> Any:
    if not _HAS_XR:
        raise EfitCompareError(
            "xarray/zarr required to read FAIR-MAST equilibrium "
            "(pip install 'mast-freegsnke-pipeline[zarr]' or see requirements.txt)"
        )
    zpath = Path(cache_dir) / f"{group}.zarr"
    if not zpath.is_dir():
        raise FileNotFoundError(
            f"missing {zpath}: download optional group '{group}' "
            "(configs/default.json optional_groups / compare_efit_archive)"
        )
    return xr.open_zarr(zpath, consolidated=False)


def _time_coord(ds: Any) -> np.ndarray:
    for name in ("time", "time_equilibrium", "t"):
        if name in ds.coords or name in ds.dims:
            return np.asarray(ds[name].values, dtype=float)
    raise EfitCompareError("equilibrium dataset has no recognizable time coordinate")


def _nearest_index(times: np.ndarray, t_query: float) -> int:
    finite = np.isfinite(times)
    if not finite.any():
        raise EfitCompareError("equilibrium time coordinate has no finite samples")
    t = times.copy()
    t[~finite] = np.nan
    return int(np.nanargmin(np.abs(t - float(t_query))))


def _series_1d(ds: Any, name: str) -> Optional[np.ndarray]:
    if name not in ds:
        return None
    da = ds[name]
    vals = np.asarray(da.values)
    # Prefer (time,) or squeeze leading dims leaving time last
    if vals.ndim == 1:
        return vals.astype(float)
    if vals.ndim >= 2 and "time" in getattr(da, "dims", ()):
        # take first index of non-time dims for overview timeseries
        idx = []
        for d in da.dims:
            if d == "time":
                idx.append(slice(None))
            else:
                idx.append(0)
        return np.asarray(da.values[tuple(idx)], dtype=float).reshape(-1)
    return vals.reshape(vals.shape[0], -1)[:, 0].astype(float)


def _extract_lcfs_at(ds: Any, idx: int, r_name: str, z_name: str) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    if r_name not in ds or z_name not in ds:
        return None
    da_r = ds[r_name]
    da_z = ds[z_name]
    r = np.asarray(da_r.values)
    z = np.asarray(da_z.values)
    dims = list(getattr(da_r, "dims", ()))
    # Prefer explicit time axis when present
    if r.ndim == 2 and "time" in dims:
        t_axis = dims.index("time")
        rr = np.take(r, idx, axis=t_axis)
        zz = np.take(z, idx, axis=t_axis)
    elif r.ndim == 2:
        # Default: axis 0 is time when it matches a plausible time length
        n0, n1 = int(r.shape[0]), int(r.shape[1])
        if n0 >= 2 and n0 <= max(64, n1):
            rr, zz = r[idx], z[idx]
        else:
            rr, zz = r[:, idx], z[:, idx]
    elif r.ndim == 1:
        rr, zz = r, z
    else:
        rr = r.reshape(r.shape[0], -1)[idx]
        zz = z.reshape(z.shape[0], -1)[idx]
    rr = np.asarray(rr, dtype=float).ravel()
    zz = np.asarray(zz, dtype=float).ravel()
    m = np.isfinite(rr) & np.isfinite(zz)
    if m.sum() < 3:
        return None
    return rr[m], zz[m]


def _extract_psi_at(ds: Any, idx: int, psi_name: str) -> Optional[Dict[str, Any]]:
    if psi_name not in ds:
        return None
    da = ds[psi_name]
    vals = np.asarray(da.values)
    dims = list(getattr(da, "dims", []))
    # Expect something like (time, R, Z) or (time, i, j)
    if vals.ndim < 2:
        return None
    if "time" in dims:
        t_axis = dims.index("time")
        psi2d = np.take(vals, idx, axis=t_axis)
        other = [d for d in dims if d != "time"]
    else:
        psi2d = vals[idx] if vals.shape[0] > idx else vals[0]
        other = [f"dim{i}" for i in range(psi2d.ndim)]
    psi2d = np.asarray(psi2d, dtype=float)
    if psi2d.ndim != 2:
        return None
    r_coord = z_coord = None
    for cand in ("major_radius", "R", "r", "dim_R"):
        if cand in ds.coords or cand in ds:
            r_coord = np.asarray(ds[cand].values, dtype=float).ravel()
            break
    for cand in ("height", "Z", "z", "dim_Z"):
        if cand in ds.coords or cand in ds:
            z_coord = np.asarray(ds[cand].values, dtype=float).ravel()
            break
    return {
        "psi": psi2d,
        "r": r_coord,
        "z": z_coord,
        "dims": other,
    }


def _try_freegsnke_products(
    run_dir: Path,
    *,
    t_compare: Optional[float] = None,
) -> Tuple[
    Optional[Tuple[np.ndarray, np.ndarray]],
    Optional[Dict[str, Any]],
    Optional[float],
    List[str],
]:
    """Best-effort LCFS + shape targets from FreeGSNKE dumps / CSVs — never invent.

    Prefer multi-time LCFS nearest to ``t_compare`` when a timeseries exists.
    Returns ``(boundary, shape, t_freegsnke, notes)``.
    """
    from .freegsnke_lcfs import (
        freegsnke_lcfs_csv_candidates,
        freegsnke_t0_from_run,
        lcfs_at_time_from_timeseries,
        lcfs_from_dump_dict,
        load_inverse_dump,
        read_lcfs_csv,
    )
    from .shape_scorecard import extract_freegsnke_shape_targets, shape_from_lcfs_polyline

    boundary: Optional[Tuple[np.ndarray, np.ndarray]] = None
    shape: Optional[Dict[str, Any]] = None
    t_fg: Optional[float] = None
    notes: List[str] = []

    if t_compare is not None:
        ts = lcfs_at_time_from_timeseries(Path(run_dir), float(t_compare))
        if ts is not None:
            boundary, t_fg, src = ts
            notes.append(f"freegsnke_lcfs_timeseries_nearest_to_t_compare:{src}")

    if boundary is None:
        for p in freegsnke_lcfs_csv_candidates(Path(run_dir)):
            if not p.is_file():
                continue
            got = read_lcfs_csv(p)
            if got is not None:
                boundary = got
                notes.append(f"freegsnke_lcfs_csv:{p.as_posix()}")
                break

    dump = load_inverse_dump(Path(run_dir))
    if boundary is None and dump is not None:
        boundary = lcfs_from_dump_dict(dump)
        if boundary is not None:
            notes.append("freegsnke_lcfs_from_inverse_dump")

    if t_fg is None:
        t_fg = freegsnke_t0_from_run(Path(run_dir))

    for dump_name in ("inverse_dump.pkl", "forward_dump.pkl"):
        dump_path = Path(run_dir) / dump_name
        if not dump_path.exists():
            continue
        try:
            import pickle

            obj = pickle.loads(dump_path.read_bytes())
        except Exception:
            continue
        eq = None
        if isinstance(obj, dict):
            if boundary is None:
                boundary = lcfs_from_dump_dict(obj)
            eq = obj.get("eq") or obj.get("equilibrium") or obj.get("tokamak")
            if eq is None and "equilibria" in obj and isinstance(obj["equilibria"], list) and obj["equilibria"]:
                eq = obj["equilibria"][0]
            if shape is None:
                ax_r = obj.get("magnetic_axis_r")
                ax_z = obj.get("magnetic_axis_z")
                if ax_r is not None or ax_z is not None:
                    shape = {
                        "magnetic_axis_r": float(ax_r) if ax_r is not None else None,
                        "magnetic_axis_z": float(ax_z) if ax_z is not None else None,
                        "x_point_r": obj.get("x_point_r"),
                        "x_point_z": obj.get("x_point_z"),
                        "R_in_m": obj.get("R_in_m"),
                        "R_out_m": obj.get("R_out_m"),
                        "notes": ["shape_from_inverse_dump_scalars"],
                    }
        else:
            eq = getattr(obj, "eq", None) or obj
        if eq is None:
            if shape is not None:
                break
            continue
        try:
            shape = extract_freegsnke_shape_targets(eq)
            notes.append(f"freegsnke_shape_from_eq:{dump_name}")
        except Exception:
            pass
        if boundary is None:
            r = getattr(eq, "rboundary", None) or getattr(eq, "Rbound", None)
            z = getattr(eq, "zboundary", None) or getattr(eq, "Zbound", None)
            if r is not None and z is not None:
                rr = np.asarray(r, dtype=float).ravel()
                zz = np.asarray(z, dtype=float).ravel()
                m = np.isfinite(rr) & np.isfinite(zz)
                if int(m.sum()) >= 3:
                    boundary = (rr[m], zz[m])
        if boundary is not None or shape is not None:
            break

    if boundary is not None and (shape is None or shape.get("R_in_m") is None):
        z_ref = None
        if shape and shape.get("magnetic_axis_z") is not None:
            z_ref = shape.get("magnetic_axis_z")
        filled = shape_from_lcfs_polyline(boundary[0], boundary[1], z_ref=z_ref)
        if shape is None:
            shape = filled
        else:
            if shape.get("R_in_m") is None:
                shape["R_in_m"] = filled.get("R_in_m")
            if shape.get("R_out_m") is None:
                shape["R_out_m"] = filled.get("R_out_m")
            notes2 = list(shape.get("notes") or [])
            notes2.extend(filled.get("notes") or [])
            shape["notes"] = notes2
        notes.append("freegsnke_midplane_from_lcfs_polyline")

    return boundary, shape, t_fg, notes


def _try_freegsnke_boundary(run_dir: Path) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    b, _, _, _ = _try_freegsnke_products(run_dir)
    return b


def run_efit_compare(
    run_dir: Path,
    *,
    shot: int,
    cache_dir: Path,
    auth: EfitCompareAuthority,
    freegsnke_python: Optional[str] = None,
    machine_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
) -> EfitCompareReport:
    """Extract EFIT++ archive products and compare to FreeGSNKE when possible."""
    run_dir = Path(run_dir)
    out = run_dir / auth.output_relpath
    out.mkdir(parents=True, exist_ok=True)
    report = EfitCompareReport(
        output_dir=_rel(run_dir, out),
        label=auth.label,
        compare_mode=auth.compare_mode,
        psi_convention=auth.psi_convention,
    )

    readme = "\n".join(
        [
            f"Shot {shot} — FreeGSNKE vs FAIR-MAST EFIT++ archive",
            "=" * 56,
            "",
            "This folder does NOT run efit-ai / Py-EFIT.",
            "Source: FAIR-MAST Level-2 group `equilibrium` (EFIT++ derived).",
            f"Compare mode: {auth.compare_mode}",
            f"ψ convention: {auth.psi_convention} (Wb/2π)",
            f"Metrics family: {auth.validation_reference}",
            f"TokaMark reference: {auth.tokamark_reference}",
            f"Docs: {auth.fairmast_docs}",
            "",
            "Start with COMPARE.md, shape_scorecard.csv, and plots/.",
            "",
        ]
    )
    (out / "README.txt").write_text(readme, encoding="utf-8")
    report.files_written.append(_rel(run_dir, out / "README.txt"))

    t_query = _load_window_mid(run_dir)
    report.t_query = t_query
    if t_query is None:
        report.warnings.append("window_midpoint_unavailable: using first finite EFIT time")

    try:
        ds = _open_equilibrium(cache_dir, auth.equilibrium_group)
    except FileNotFoundError as e:
        report.errors.append(str(e))
        report.fix_hint = (
            "Ensure optional_groups includes 'equilibrium' and re-run download, "
            "or disable compare_efit_archive."
        )
        (out / "COMPARE.json").write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        report.files_written.append(_rel(run_dir, out / "COMPARE.json"))
        return report
    except EfitCompareError as e:
        report.errors.append(str(e))
        report.fix_hint = str(e)
        (out / "COMPARE.json").write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        report.files_written.append(_rel(run_dir, out / "COMPARE.json"))
        return report

    report.equilibrium_path = str(Path(cache_dir) / f"{auth.equilibrium_group}.zarr")
    report.available_vars = sorted(str(v) for v in ds.data_vars)

    try:
        times = _time_coord(ds)
    except EfitCompareError as e:
        report.errors.append(str(e))
        ds.close()
        (out / "COMPARE.json").write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
        return report

    if t_query is None:
        finite = np.where(np.isfinite(times))[0]
        idx = int(finite[0]) if len(finite) else 0
        t_query = float(times[idx]) if len(times) else 0.0
        report.t_query = t_query
    else:
        idx = _nearest_index(times, t_query)
    report.t_efit = float(times[idx]) if idx < len(times) else None

    # Align scorecard time: window-mid EFIT vs FreeGSNKE inverse t0 was a major
    # false-divergence source. Prefer FG timeseries @ window mid; else snap EFIT
    # to FreeGSNKE t0 when only a single-time LCFS exists.
    from .freegsnke_lcfs import freegsnke_lcfs_timeseries_candidates, freegsnke_t0_from_run

    t_fg_probe = freegsnke_t0_from_run(run_dir)
    has_fg_timeseries = any(p.is_file() for p in freegsnke_lcfs_timeseries_candidates(run_dir))
    if has_fg_timeseries:
        report.time_align_note = (
            "efit_at_window_midpoint_freegsnke_lcfs_timeseries_nearest"
        )
    elif t_fg_probe is not None and report.t_efit is not None:
        idx = _nearest_index(times, float(t_fg_probe))
        report.t_efit = float(times[idx]) if idx < len(times) else report.t_efit
        report.time_align_note = (
            "scorecard_efit_nearest_to_freegsnke_t0_not_window_mid"
        )
        report.warnings.append(report.time_align_note)
        report.warnings.append(
            f"freegsnke_t0={float(t_fg_probe):.6f}s window_mid_query={float(t_query):.6f}s"
        )
    else:
        report.time_align_note = "efit_at_window_midpoint_freegsnke_time_unknown"

    # Shape scalar timeseries CSV
    scalar_cols: Dict[str, np.ndarray] = {"time": times}
    for name in auth.shape_scalars:
        s = _series_1d(ds, name)
        if s is None:
            report.missing_vars.append(name)
            continue
        if len(s) != len(times):
            report.warnings.append(f"length_mismatch:{name}:{len(s)}!={len(times)}")
            # pad / trim carefully
            n = min(len(s), len(times))
            s2 = np.full(len(times), np.nan, dtype=float)
            s2[:n] = s[:n]
            scalar_cols[name] = s2
        else:
            scalar_cols[name] = s
    scalars_path = out / "efit_shape_timeseries.csv"
    pd.DataFrame(scalar_cols).to_csv(scalars_path, index=False)
    report.files_written.append(_rel(run_dir, scalars_path))

    # Snapshot at nearest time
    snap: Dict[str, Any] = {
        "shot": int(shot),
        "t_query_s": report.t_query,
        "t_efit_s": report.t_efit,
        "time_index": idx,
        "label": auth.label,
        "scalars": {},
    }
    for name in auth.shape_scalars:
        if name in scalar_cols and name != "time":
            v = float(scalar_cols[name][idx]) if idx < len(scalar_cols[name]) else float("nan")
            snap["scalars"][name] = v if math.isfinite(v) else None
    snap_path = out / "efit_snapshot.json"
    snap_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    report.files_written.append(_rel(run_dir, snap_path))

    # LCFS
    lcfs = None
    if len(auth.lcfs_vars) >= 2:
        lcfs = _extract_lcfs_at(ds, idx, auth.lcfs_vars[0], auth.lcfs_vars[1])
    if lcfs is None:
        report.missing_vars.append("lcfs_r/lcfs_z")
        report.warnings.append("efit_lcfs_unavailable_at_selected_time")
    else:
        rr, zz = lcfs
        lcfs_csv = out / "efit_lcfs.csv"
        pd.DataFrame({"R": rr, "Z": zz}).to_csv(lcfs_csv, index=False)
        report.files_written.append(_rel(run_dir, lcfs_csv))

    # Psi map (optional)
    psi_pack = _extract_psi_at(ds, idx, auth.psi_var)
    if psi_pack is None:
        report.missing_vars.append(auth.psi_var)
    else:
        npz_path = out / "efit_psi.npz"
        save_kw: Dict[str, Any] = {"psi": psi_pack["psi"]}
        if psi_pack.get("r") is not None:
            save_kw["R"] = psi_pack["r"]
        if psi_pack.get("z") is not None:
            save_kw["Z"] = psi_pack["z"]
        np.savez_compressed(npz_path, **save_kw)
        report.files_written.append(_rel(run_dir, npz_path))

    # FreeGSNKE boundary + shape targets (time-aligned)
    t_cmp = report.t_efit if report.t_efit is not None else t_query
    fg, fg_shape, t_fg, fg_notes = _try_freegsnke_products(run_dir, t_compare=t_cmp)
    if fg is None:
        # Older dumps lacked lcfs_R/CSV — recover via FreeGSNKE venv when possible
        try:
            from .freegsnke_lcfs import recover_lcfs_via_freegsnke_venv

            ma = Path(machine_dir) if machine_dir is not None else None
            if ma is None:
                for cand in (
                    Path(run_dir) / "inputs" / "machine_authority",
                    Path(run_dir).resolve().parents[1] / "machine_authority",
                    Path(__file__).resolve().parents[2] / "machine_authority",
                ):
                    if (cand / "active_coils.pickle").is_file():
                        ma = cand
                        break
            if ma is not None:
                rec = recover_lcfs_via_freegsnke_venv(
                    run_dir,
                    machine_dir=ma,
                    freegsnke_python=freegsnke_python,
                    repo_root=repo_root,
                )
                if rec.get("ok"):
                    report.warnings.append("freegsnke_lcfs_recovered_from_inverse_dump")
                    fg, fg_shape, t_fg, fg_notes = _try_freegsnke_products(
                        run_dir, t_compare=t_cmp
                    )
                else:
                    report.warnings.append(
                        "freegsnke_lcfs_recover_failed:"
                        + ",".join(str(x) for x in (rec.get("errors") or [])[:2])
                    )
        except Exception as e:
            report.warnings.append(f"freegsnke_lcfs_recover_exception:{type(e).__name__}:{e}")
    for n in fg_notes:
        report.warnings.append(n)
    report.t_freegsnke = t_fg
    report.freegsnke_boundary_available = fg is not None
    report.compare_mode = auth.compare_mode
    report.psi_convention = auth.psi_convention
    snap["t_freegsnke_s"] = t_fg
    snap["time_align_note"] = report.time_align_note
    snap_path.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")

    from .shape_scorecard import build_shape_scorecard

    scorecard = build_shape_scorecard(
        efit_scalars=snap.get("scalars") or {},
        efit_lcfs=lcfs,
        freegsnke_lcfs=fg,
        freegsnke_shape=fg_shape,
        psi_convention=auth.psi_convention,
        compare_mode=auth.compare_mode,
        validation_reference=auth.validation_reference,
        t_efit=report.t_efit,
        t_freegsnke=t_fg,
        time_align_note=report.time_align_note,
    )
    report.shape_scorecard = scorecard
    score_path = out / "shape_scorecard.json"
    score_path.write_text(json.dumps(scorecard, indent=2) + "\n", encoding="utf-8")
    report.files_written.append(_rel(run_dir, score_path))
    # CSV rows for experts
    score_csv = out / "shape_scorecard.csv"
    pd.DataFrame(scorecard.get("rows") or []).to_csv(score_csv, index=False)
    report.files_written.append(_rel(run_dir, score_csv))

    plots_dir = out / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    if _HAS_MPL:
        # Shape timeseries (first few available)
        plot_vars = [c for c in scalar_cols if c != "time" and np.isfinite(scalar_cols[c]).sum() >= 2][:6]
        if plot_vars:
            fig, axes = plt.subplots(len(plot_vars), 1, figsize=(9, 2.2 * len(plot_vars)), sharex=True)
            if len(plot_vars) == 1:
                axes = [axes]
            for ax, name in zip(axes, plot_vars):
                ax.plot(times, scalar_cols[name], lw=1.2, label="EFIT++ archive")
                if report.t_efit is not None:
                    ax.axvline(report.t_efit, color="0.4", ls="--", lw=0.9, label="compare time")
                ax.set_ylabel(name)
                ax.grid(True, alpha=0.35)
                ax.legend(loc="best", fontsize=7, frameon=False)
            axes[-1].set_xlabel("time (s)")
            fig.suptitle(f"Shot {shot}: FAIR-MAST EFIT++ shape scalars")
            fig.tight_layout()
            p = plots_dir / "efit_shape_timeseries.png"
            fig.savefig(p, dpi=140, bbox_inches="tight")
            plt.close(fig)
            report.plots_written.append(_rel(run_dir, p))

        if lcfs is not None:
            fig, ax = plt.subplots(figsize=(6.2, 7.0))
            rr, zz = lcfs
            ax.plot(rr, zz, "k-", lw=1.5, label="EFIT++ LCFS (archive)")
            if fg is not None:
                ax.plot(fg[0], fg[1], "r--", lw=1.3, label="FreeGSNKE boundary")
            ax.set_aspect("equal", adjustable="datalim")
            ax.set_xlabel("R (m)")
            ax.set_ylabel("Z (m)")
            _title = f"Shot {shot}: LCFS compare"
            if report.t_efit is not None:
                _title += f" · EFIT t≈{report.t_efit:.4f}s"
            if report.t_freegsnke is not None:
                _title += f" · FG t≈{report.t_freegsnke:.4f}s"
            if report.time_align_note:
                _title += f"\n({report.time_align_note})"
            ax.set_title(_title, fontsize=10)
            ax.grid(True, alpha=0.35)
            ax.legend(loc="best", fontsize=8, frameon=False)
            fig.tight_layout()
            p = plots_dir / "lcfs_compare.png"
            fig.savefig(p, dpi=140, bbox_inches="tight")
            plt.close(fig)
            report.plots_written.append(_rel(run_dir, p))

        if psi_pack is not None:
            fig, ax = plt.subplots(figsize=(6.5, 6.5))
            psi = psi_pack["psi"]
            extent = None
            r_c, z_c = psi_pack.get("r"), psi_pack.get("z")
            if r_c is not None and z_c is not None and len(r_c) > 1 and len(z_c) > 1:
                # Heuristic: if psi shape matches (nZ, nR) or (nR, nZ)
                if psi.shape == (len(z_c), len(r_c)):
                    extent = [float(r_c.min()), float(r_c.max()), float(z_c.min()), float(z_c.max())]
                    im = ax.imshow(psi, origin="lower", extent=extent, aspect="equal")
                elif psi.shape == (len(r_c), len(z_c)):
                    extent = [float(r_c.min()), float(r_c.max()), float(z_c.min()), float(z_c.max())]
                    im = ax.imshow(psi.T, origin="lower", extent=extent, aspect="equal")
                else:
                    im = ax.imshow(psi, origin="lower", aspect="auto")
            else:
                im = ax.imshow(psi, origin="lower", aspect="auto")
            fig.colorbar(
                im,
                ax=ax,
                fraction=0.046,
                pad=0.04,
                label="ψ (EFIT++ archive, Wb/2π)",
            )
            if lcfs is not None:
                ax.plot(lcfs[0], lcfs[1], "w-", lw=1.2, label="EFIT++ LCFS")
            if fg is not None:
                ax.plot(fg[0], fg[1], "r--", lw=1.2, label="FreeGSNKE")
            ax.set_xlabel("R (m)" if extent else "i")
            ax.set_ylabel("Z (m)" if extent else "j")
            ax.set_title(f"Shot {shot}: EFIT++ ψ map (archive, Wb/2π)")
            ax.legend(loc="best", fontsize=7, frameon=False)
            fig.tight_layout()
            p = plots_dir / "efit_psi.png"
            fig.savefig(p, dpi=140, bbox_inches="tight")
            plt.close(fig)
            report.plots_written.append(_rel(run_dir, p))

    # Classic MAST FreeGSNKE | EFIT++ side-by-side animation (FreeGSNKE README-style)
    try:
        from .efit_side_by_side import write_freegsnke_efit_side_by_side_gif

        n_sbs = int(getattr(auth, "side_by_side_n_frames", 16) or 16)
        fps_sbs = float(getattr(auth, "side_by_side_fps", 2.0) or 2.0)
        if bool(getattr(auth, "write_side_by_side_gif", True)) and _HAS_MPL:
            sbs = write_freegsnke_efit_side_by_side_gif(
                run_dir=run_dir,
                shot=int(shot),
                ds=ds,
                times=times,
                lcfs_r_name=auth.lcfs_vars[0] if auth.lcfs_vars else "lcfs_r",
                lcfs_z_name=auth.lcfs_vars[1] if len(auth.lcfs_vars) > 1 else "lcfs_z",
                psi_var=auth.psi_var,
                out_dir=plots_dir,
                n_frames=n_sbs,
                fps=fps_sbs,
            )
            report.warnings.extend([f"side_by_side:{n}" for n in (sbs.get("notes") or [])])
            if sbs.get("gif_rel"):
                report.plots_written.append(str(sbs["gif_rel"]))
            if sbs.get("meta_rel"):
                report.files_written.append(str(sbs["meta_rel"]))
            for fr in sbs.get("frame_rels") or []:
                report.files_written.append(str(fr))
            if not sbs.get("ok"):
                for e in sbs.get("errors") or []:
                    report.warnings.append(f"side_by_side_gif:{e}")
    except Exception as e:
        report.warnings.append(f"side_by_side_gif_failed:{e}")

    # COMPARE.md
    md_lines = [
        f"# Shot {shot}: FreeGSNKE vs FAIR-MAST EFIT++",
        "",
        f"- **Archive label:** {auth.label}",
        f"- **Compare mode:** `{auth.compare_mode}`",
        f"- **ψ convention:** `{auth.psi_convention}` (FreeGSNKE & EFIT++: Wb/2π)",
        f"- **Validation metrics reference:** {auth.validation_reference}",
        f"- **t_query (window mid):** `{report.t_query}`",
        f"- **t_efit (nearest):** `{report.t_efit}`",
        f"- **t_freegsnke:** `{report.t_freegsnke}`",
        f"- **time align:** `{report.time_align_note}`",
        f"- **FreeGSNKE boundary available:** `{report.freegsnke_boundary_available}`",
        "",
        "## Mode honesty",
        "",
        scorecard.get("compare_mode_note", ""),
        "",
        scorecard.get("psi_convention_note", ""),
        "",
        "## Shape scorecard (Pentland et al. metric family)",
        "",
        "| Quantity | EFIT++ archive | FreeGSNKE | Δ (FG−EFIT) | Unit |",
        "|----------|----------------|-----------|-------------|------|",
    ]
    for row in scorecard.get("rows") or []:
        md_lines.append(
            "| `{q}` | {e} | {f} | {d} | {u} |".format(
                q=row.get("quantity"),
                e=row.get("efit_archive") if row.get("efit_archive") is not None else "—",
                f=row.get("freegsnke") if row.get("freegsnke") is not None else "—",
                d=row.get("delta_freegsnke_minus_efit")
                if row.get("delta_freegsnke_minus_efit") is not None
                else "—",
                u=row.get("unit") or "",
            )
        )
    md_lines += [
        "",
        f"_Rows with both sides populated: {scorecard.get('n_rows_with_both', 0)}_",
        "",
        "## Snapshot scalars (EFIT++ archive)",
        "",
        "| Quantity | Value |",
        "|----------|-------|",
    ]
    for k, v in (snap.get("scalars") or {}).items():
        md_lines.append(f"| `{k}` | {v if v is not None else '—'} |")
    md_lines += [
        "",
        "## Files",
        "",
        "- `shape_scorecard.json` / `shape_scorecard.csv`",
        "- `efit_shape_timeseries.csv`",
        "- `efit_snapshot.json`",
        "- `efit_lcfs.csv` (when available)",
        "- `efit_psi.npz` (when available)",
        "- `plots/` (incl. `freegsnke_efit_side_by_side.gif` when written)",
        "",
        "## Honesty",
        "",
        "These products are **archived EFIT++** from FAIR-MAST Level-2, not a fresh efit-ai / Py-EFIT solve.",
        "TokaMark uses the same derived equilibrium signals as ML targets.",
        "Shape metrics follow the family used in arXiv:2407.12432; agreement like that paper requires",
        "matched EFIT++ currents+profiles into FreeGSNKE **forward** (not enabled here).",
        "The side-by-side GIF mirrors FreeGSNKE's public MAST-U demo layout for **classic MAST**",
        "using FAIR-MAST archive reconstructions (not a live EFIT++ run).",
        "",
    ]
    if report.warnings:
        md_lines.append("## Warnings")
        md_lines.append("")
        md_lines.extend(f"- {w}" for w in report.warnings)
        md_lines.append("")
    (out / "COMPARE.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    report.files_written.append(_rel(run_dir, out / "COMPARE.md"))

    report.ok = len(report.errors) == 0 and (
        "efit_shape_timeseries.csv" in " ".join(report.files_written)
    )
    try:
        ds.close()
    except Exception:
        pass

    (out / "COMPARE.json").write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    report.files_written.append(_rel(run_dir, out / "COMPARE.json"))
    return report
