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
    authority_version: str = "1.0"
    source: str = "fairmast_level2_equilibrium"
    label: str = "FAIR-MAST EFIT++ archive (not efit-ai Fortran)"
    tokamark_reference: str = "https://github.com/UKAEA-IBM-STFC-Fusion-FMs/tokamark"
    fairmast_docs: str = "https://mastapp.site/level2-data.html"
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
    notes: str = "ADR-002"

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
        if not str(self.output_relpath).strip():
            raise EfitCompareError("output_relpath required")
        if not self.shape_scalars:
            raise EfitCompareError("shape_scalars must be non-empty (declare which EFIT fields to export)")

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
        authority_version=str(obj.get("authority_version", "1.0")),
        source=str(obj.get("source", "fairmast_level2_equilibrium")),
        label=str(obj.get("label", "FAIR-MAST EFIT++ archive (not efit-ai Fortran)")),
        tokamark_reference=str(
            obj.get(
                "tokamark_reference",
                "https://github.com/UKAEA-IBM-STFC-Fusion-FMs/tokamark",
            )
        ),
        fairmast_docs=str(obj.get("fairmast_docs", "https://mastapp.site/level2-data.html")),
        equilibrium_group=str(obj.get("equilibrium_group", "equilibrium")),
        output_relpath=str(obj.get("output_relpath", "04_efit_compare")),
        fail_closed_if_missing=bool(obj.get("fail_closed_if_missing", False)),
        shape_scalars=tuple(obj.get("shape_scalars") or EfitCompareAuthority().shape_scalars),
        lcfs_vars=tuple(obj.get("lcfs_vars") or ("lcfs_r", "lcfs_z")),
        psi_var=str(obj.get("psi_var", "psi")),
        time_policy=str(obj.get("time_policy", "nearest_to_window_midpoint")),
        notes=str(obj.get("notes", "ADR-002")),
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
    equilibrium_path: str = ""
    t_query: Optional[float] = None
    t_efit: Optional[float] = None
    files_written: List[str] = field(default_factory=list)
    plots_written: List[str] = field(default_factory=list)
    available_vars: List[str] = field(default_factory=list)
    missing_vars: List[str] = field(default_factory=list)
    freegsnke_boundary_available: bool = False
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
    r = np.asarray(ds[r_name].values)
    z = np.asarray(ds[z_name].values)
    # Common layouts: (time, n) or (n, time)
    if r.ndim == 2:
        if r.shape[0] > idx and r.shape[0] <= r.shape[1] * 2:
            # likely (time, n)
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


def _try_freegsnke_boundary(run_dir: Path) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Best-effort LCFS from FreeGSNKE dumps / CSVs — never invent."""
    # Optional CSV if a future exporter writes it
    for rel in (
        "03_reconstruction/freegsnke_lcfs.csv",
        "synthetic/freegsnke_lcfs.csv",
        "presentation/freegsnke_lcfs.csv",
    ):
        p = Path(run_dir) / rel
        if p.exists():
            try:
                df = pd.read_csv(p)
                if {"R", "Z"}.issubset(df.columns) or {"r", "z"}.issubset({c.lower() for c in df.columns}):
                    cols = {c.lower(): c for c in df.columns}
                    rr = df[cols.get("r", "R")].to_numpy(dtype=float)
                    zz = df[cols.get("z", "Z")].to_numpy(dtype=float)
                    m = np.isfinite(rr) & np.isfinite(zz)
                    if m.sum() >= 3:
                        return rr[m], zz[m]
            except Exception:
                pass
    # Pickle introspection (optional)
    for dump_name in ("inverse_dump.pkl", "03_reconstruction/inverse_dump.pkl"):
        dump = Path(run_dir) / dump_name
        if not dump.exists():
            continue
        try:
            import pickle

            obj = pickle.loads(dump.read_bytes())
        except Exception:
            continue
        eq = None
        if isinstance(obj, dict):
            eq = obj.get("eq") or obj.get("equilibrium") or obj.get("tokamak")
        else:
            eq = getattr(obj, "eq", None) or obj
        for attr in ("rboundary", "zboundary", "Rbound", "Zbound"):
            pass
        r = getattr(eq, "rboundary", None) if eq is not None else None
        z = getattr(eq, "zboundary", None) if eq is not None else None
        if r is None and eq is not None:
            r = getattr(eq, "Rbound", None)
            z = getattr(eq, "Zbound", None)
        if r is not None and z is not None:
            rr = np.asarray(r, dtype=float).ravel()
            zz = np.asarray(z, dtype=float).ravel()
            m = np.isfinite(rr) & np.isfinite(zz)
            if m.sum() >= 3:
                return rr[m], zz[m]
    return None


def run_efit_compare(
    run_dir: Path,
    *,
    shot: int,
    cache_dir: Path,
    auth: EfitCompareAuthority,
) -> EfitCompareReport:
    """Extract EFIT++ archive products and compare to FreeGSNKE when possible."""
    run_dir = Path(run_dir)
    out = run_dir / auth.output_relpath
    out.mkdir(parents=True, exist_ok=True)
    report = EfitCompareReport(
        output_dir=_rel(run_dir, out),
        label=auth.label,
    )

    readme = "\n".join(
        [
            f"Shot {shot} — FreeGSNKE vs FAIR-MAST EFIT++ archive",
            "=" * 56,
            "",
            "This folder does NOT run efit-ai Fortran.",
            "Source: FAIR-MAST Level-2 group `equilibrium` (EFIT++ derived).",
            f"TokaMark reference: {auth.tokamark_reference}",
            f"Docs: {auth.fairmast_docs}",
            "",
            "Start with COMPARE.md and plots/.",
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

    # FreeGSNKE boundary overlay
    fg = _try_freegsnke_boundary(run_dir)
    report.freegsnke_boundary_available = fg is not None

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
            ax.set_title(
                f"Shot {shot}: LCFS compare @ t≈{report.t_efit:.4f}s"
                if report.t_efit is not None
                else f"Shot {shot}: LCFS"
            )
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
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04, label="ψ (EFIT++ archive)")
            if lcfs is not None:
                ax.plot(lcfs[0], lcfs[1], "w-", lw=1.2, label="EFIT++ LCFS")
            if fg is not None:
                ax.plot(fg[0], fg[1], "r--", lw=1.2, label="FreeGSNKE")
            ax.set_xlabel("R (m)" if extent else "i")
            ax.set_ylabel("Z (m)" if extent else "j")
            ax.set_title(f"Shot {shot}: EFIT++ ψ map (archive)")
            ax.legend(loc="best", fontsize=7, frameon=False)
            fig.tight_layout()
            p = plots_dir / "efit_psi.png"
            fig.savefig(p, dpi=140, bbox_inches="tight")
            plt.close(fig)
            report.plots_written.append(_rel(run_dir, p))

    # COMPARE.md
    md_lines = [
        f"# Shot {shot}: FreeGSNKE vs FAIR-MAST EFIT++",
        "",
        f"- **Archive label:** {auth.label}",
        f"- **t_query (window mid):** `{report.t_query}`",
        f"- **t_efit (nearest):** `{report.t_efit}`",
        f"- **FreeGSNKE boundary available:** `{report.freegsnke_boundary_available}`",
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
        "- `efit_shape_timeseries.csv`",
        "- `efit_snapshot.json`",
        "- `efit_lcfs.csv` (when available)",
        "- `efit_psi.npz` (when available)",
        "- `plots/`",
        "",
        "## Honesty",
        "",
        "These products are **archived EFIT++** from FAIR-MAST Level-2, not a fresh efit-ai solve.",
        "TokaMark uses the same derived equilibrium signals as ML targets.",
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
