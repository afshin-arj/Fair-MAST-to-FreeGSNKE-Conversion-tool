"""Optional FAIR-MAST Level-2 diagnostics → measured pack (CSV + plots).

Groups mirror https://mastapp.site/level2-data.html beyond FreeGSNKE inputs.
Missing groups are WARN-only (never blocking). Cache hits are reused; no inventing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from mast_freegsnke.experimental_data import (
    ExperimentalDataReport,
    _HAS_MPL,
    _rel,
    _save_fig,
    _shade_window,
    _style_axes,
)

# Catalog families + folder layout under 02_measured_data/
# (prefix used for plot filenames so UI can classify them)
DIAGNOSTIC_SPECS: Tuple[Dict[str, Any], ...] = (
    {
        "group": "summary",
        "folder": "06_summary",
        "plot_prefix": "06",
        "label": "Summary profiles",
        "vars_1d": None,  # all 1-D time series (capped)
        "max_1d": 16,
    },
    {
        "group": "pulse_schedule",
        "folder": "07_pulse_schedule",
        "plot_prefix": "07",
        "label": "Pulse schedule",
        "vars_1d": ("i_plasma", "n_e_line"),
    },
    {
        "group": "spectrometer_visible",
        "folder": "08_spectrometer_visible",
        "plot_prefix": "08",
        "label": "Spectrometer (visible)",
        "vars_1d": ("filter_spectrometer_dalpha_voltage",),
        "vars_line": (("filter_spectrometer_bes_voltage", 0),),
    },
    {
        "group": "soft_x_rays",
        "folder": "09_soft_x_rays",
        "plot_prefix": "09",
        "label": "Soft X-rays",
        "vars_1d": ("tangential_cam", "horizontal_cam_lower", "horizontal_cam_upper"),
        "max_channels": 12,
    },
    {
        "group": "thomson_scattering",
        "folder": "10_thomson_scattering",
        "plot_prefix": "10",
        "label": "Thomson scattering",
        "vars_1d": ("t_e_core", "n_e_core"),
        "vars_2d": ("t_e", "n_e", "p_e"),
        "y_coord": "major_radius",
    },
    {
        "group": "charge_exchange",
        "folder": "11_charge_exchange",
        "plot_prefix": "11",
        "label": "CXRS (charge exchange)",
        "vars_2d": ("t_i", "v_i"),
        "y_coord": "major_radius",
    },
    {
        "group": "gas_injection",
        "folder": "12_gas_injection",
        "plot_prefix": "12",
        "label": "Gas injection",
        "vars_1d": ("inboard_total", "outboard_total", "pressure", "total_injected"),
    },
    {
        "group": "equilibrium",
        "folder": "13_equilibrium_l2",
        "plot_prefix": "13",
        "label": "Equilibrium archive (L2 scalars)",
        "vars_1d": (
            "beta_tor_normal",
            "wmhd",
            "li",
            "elongation",
            "triangularity_upper",
            "q95",
            "vloop_dynamic",
            "ip_rating",
        ),
    },
)

# Public list for config / docs
OPTIONAL_DIAGNOSTIC_GROUPS: Tuple[str, ...] = tuple(s["group"] for s in DIAGNOSTIC_SPECS)


def _open_group(zarr_path: Path):
    import xarray as xr

    return xr.open_zarr(zarr_path, consolidated=False)


def _time_name(da) -> Optional[str]:
    for c in ("time", "time_bes", "time_mirnov", "time_saddle", "time_omaha"):
        if c in da.dims or c in da.coords:
            return c
    for d in da.dims:
        if "time" in str(d).lower():
            return str(d)
    return None


def _as_1d_frame(da, *, max_channels: int = 16) -> Optional[pd.DataFrame]:
    """Flatten a DataArray to a CSV-friendly time × channels table."""
    tname = _time_name(da)
    if tname is None:
        return None
    try:
        vals = da
        # Pick first index along non-time dims beyond one channel axis
        extra = [d for d in vals.dims if d != tname]
        if len(extra) >= 2:
            # Keep time + first channel-like dim; isel the rest at 0
            keep = extra[0]
            for d in extra[1:]:
                vals = vals.isel({d: 0})
            extra = [keep]
        if len(extra) == 1:
            ch = extra[0]
            n = int(vals.sizes[ch])
            take = min(n, max_channels)
            t = np.asarray(vals[tname].values, dtype=float)
            data = {"time": t}
            labels = vals[ch].values if ch in vals.coords else range(take)
            for i in range(take):
                lab = labels[i] if i < len(labels) else i
                col = f"{da.name}_{lab}" if da.name else str(lab)
                data[str(col)] = np.asarray(vals.isel({ch: i}).values, dtype=float)
            return pd.DataFrame(data)
        # pure 1-D
        t = np.asarray(vals[tname].values, dtype=float)
        y = np.asarray(vals.values, dtype=float).ravel()
        if t.size != y.size:
            n = min(t.size, y.size)
            t, y = t[:n], y[:n]
        name = str(da.name or "value")
        return pd.DataFrame({"time": t, name: y})
    except Exception:
        return None


def _as_2d_long(da, *, y_coord: str, max_rows: int = 80_000) -> Optional[pd.DataFrame]:
    tname = _time_name(da)
    if tname is None or y_coord not in da.dims:
        return None
    try:
        vals = da
        extra = [d for d in vals.dims if d not in (tname, y_coord)]
        for d in extra:
            vals = vals.isel({d: 0})
        t = np.asarray(vals[tname].values, dtype=float)
        r = np.asarray(vals[y_coord].values, dtype=float)
        z = np.asarray(vals.values, dtype=float)
        # Downsample to keep CSV portable
        nt, nr = z.shape if z.ndim == 2 else (len(t), 1)
        stride_t = max(1, int(np.ceil(nt * nr / max_rows)))
        t_i = np.arange(0, nt, stride_t)
        tt, rr = np.meshgrid(t[t_i], r, indexing="ij")
        zz = z[t_i, :]
        return pd.DataFrame(
            {
                "time": tt.ravel(),
                y_coord: rr.ravel(),
                str(da.name or "value"): zz.ravel(),
            }
        )
    except Exception:
        return None


def _write_csv(df: pd.DataFrame, path: Path, report: ExperimentalDataReport, run_dir: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    rel = _rel(run_dir, path)
    report.files_written.append(rel)
    return rel


def _plot_1d_csv(
    csv_path: Path,
    out_png: Path,
    *,
    shot: int,
    title: str,
    ylabel: str,
    window: Optional[Tuple[float, float]],
    report: ExperimentalDataReport,
    run_dir: Path,
    max_series: int = 10,
) -> None:
    if not _HAS_MPL or not csv_path.is_file():
        return
    try:
        import matplotlib.pyplot as plt

        df = pd.read_csv(csv_path)
        if "time" not in df.columns:
            return
        cols = [c for c in df.columns if c != "time"][:max_series]
        if not cols:
            return
        fig, ax = plt.subplots(figsize=(9.5, 4.6))
        _shade_window(ax, window)
        t = df["time"].to_numpy(dtype=float)
        for c in cols:
            y = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
            if np.isfinite(y).sum() >= 2:
                ax.plot(t, y, lw=1.0, label=str(c)[:40])
        _style_axes(ax, title=f"Shot {shot}: {title}", xlabel="time (s)", ylabel=ylabel)
        _save_fig(fig, out_png, report, run_dir)
    except Exception as e:
        report.warnings.append(f"diag_plot_1d_failed:{csv_path.name}:{type(e).__name__}:{e}")


def _plot_2d_da(
    da,
    out_png: Path,
    *,
    shot: int,
    title: str,
    y_coord: str,
    window: Optional[Tuple[float, float]],
    report: ExperimentalDataReport,
    run_dir: Path,
) -> None:
    if not _HAS_MPL:
        return
    tname = _time_name(da)
    if tname is None or y_coord not in da.dims:
        return
    try:
        import matplotlib.pyplot as plt

        vals = da
        for d in [d for d in vals.dims if d not in (tname, y_coord)]:
            vals = vals.isel({d: 0})
        t = np.asarray(vals[tname].values, dtype=float)
        r = np.asarray(vals[y_coord].values, dtype=float)
        z = np.asarray(vals.values, dtype=float)
        # Cap resolution for speed / file size
        if t.size > 400:
            step = int(np.ceil(t.size / 400))
            t = t[::step]
            z = z[::step, :]
        if r.size > 120:
            step = int(np.ceil(r.size / 120))
            r = r[::step]
            z = z[:, ::step]
        fig, ax = plt.subplots(figsize=(9.5, 4.8))
        pcm = ax.pcolormesh(t, r, z.T, shading="auto", cmap="viridis")
        fig.colorbar(pcm, ax=ax, pad=0.02)
        if window:
            ax.axvline(window[0], color="w", ls="--", lw=0.8, alpha=0.7)
            ax.axvline(window[1], color="w", ls="--", lw=0.8, alpha=0.7)
        ax.set_title(f"Shot {shot}: {title}")
        ax.set_xlabel("time (s)")
        ax.set_ylabel(y_coord)
        _save_fig(fig, out_png, report, run_dir)
    except Exception as e:
        report.warnings.append(f"diag_plot_2d_failed:{da.name}:{type(e).__name__}:{e}")


def export_optional_diagnostics(
    *,
    cache_dir: Optional[Path],
    measured_root: Path,
    run_dir: Path,
    shot: int,
    window: Optional[Tuple[float, float]],
    plots: bool,
    report: ExperimentalDataReport,
    catalog: Dict[str, Any],
    groups: Optional[Sequence[str]] = None,
) -> None:
    """Export optional L2 diagnostic groups into 02_measured_data/. Warn-only on miss."""
    if cache_dir is None:
        report.warnings.append("optional_diagnostics_skip:no_cache_dir")
        return
    cache_dir = Path(cache_dir)
    wanted = set(groups) if groups is not None else set(OPTIONAL_DIAGNOSTIC_GROUPS)
    plots_dir = measured_root / "05_plots"
    status: Dict[str, Any] = {"groups": {}}

    for spec in DIAGNOSTIC_SPECS:
        gname = str(spec["group"])
        if gname not in wanted:
            continue
        zpath = cache_dir / f"{gname}.zarr"
        folder = measured_root / str(spec["folder"])
        folder.mkdir(parents=True, exist_ok=True)
        entry: Dict[str, Any] = {
            "level": "L2",
            "kind": "measured_optional",
            "group": gname,
            "label": spec["label"],
            "source": f"{gname}.zarr",
            "available": False,
        }
        if not zpath.is_dir():
            msg = f"optional_group_missing:{gname}"
            report.warnings.append(msg)
            entry["warning"] = msg
            status["groups"][gname] = entry
            catalog["families"][f"diag_{gname}"] = entry
            (folder / "MISSING.txt").write_text(
                f"{gname} not present under {cache_dir.name}/ for shot {shot}.\n"
                "Optional FAIR-MAST Level-2 group — warning only (not blocking).\n"
                "See https://mastapp.site/level2-data.html\n",
                encoding="utf-8",
            )
            report.files_written.append(_rel(run_dir, folder / "MISSING.txt"))
            continue
        try:
            ds = _open_group(zpath)
        except Exception as e:
            msg = f"optional_group_open_failed:{gname}:{type(e).__name__}:{e}"
            report.warnings.append(msg)
            entry["warning"] = msg
            status["groups"][gname] = entry
            catalog["families"][f"diag_{gname}"] = entry
            continue

        entry["available"] = True
        written: List[str] = []
        try:
            # --- 1-D / channel series ---
            vars_1d = spec.get("vars_1d")
            names: List[str]
            if vars_1d is None:
                names = []
                for n in list(ds.data_vars):
                    da = ds[n]
                    if _time_name(da) and len(da.dims) <= 2:
                        names.append(str(n))
                    if len(names) >= int(spec.get("max_1d", 16)):
                        break
            else:
                names = [str(n) for n in vars_1d if n in ds]

            max_ch = int(spec.get("max_channels", 16))
            for n in names:
                da = ds[n]
                df = _as_1d_frame(da, max_channels=max_ch)
                if df is None or df.empty:
                    report.warnings.append(f"optional_csv_skip:{gname}:{n}")
                    continue
                rel = _write_csv(df, folder / f"{n}.csv", report, run_dir)
                written.append(rel)
                if plots:
                    _plot_1d_csv(
                        folder / f"{n}.csv",
                        plots_dir / f"{spec['plot_prefix']}_{gname}_{n}.png",
                        shot=shot,
                        title=f"{spec['label']}: {n}",
                        ylabel=str(n),
                        window=window,
                        report=report,
                        run_dir=run_dir,
                    )

            # Optional isel lines (e.g. BES channel 0)
            for item in spec.get("vars_line") or ():
                if not isinstance(item, (tuple, list)) or len(item) < 2:
                    continue
                n, idx = str(item[0]), int(item[1])
                if n not in ds:
                    continue
                da = ds[n]
                # pick first non-time dim
                tname = _time_name(da)
                ch_dims = [d for d in da.dims if d != tname]
                if not ch_dims:
                    continue
                try:
                    da0 = da.isel({ch_dims[0]: idx})
                except Exception:
                    continue
                df = _as_1d_frame(da0, max_channels=1)
                if df is None:
                    continue
                stem = f"{n}_ch{idx}"
                rel = _write_csv(df, folder / f"{stem}.csv", report, run_dir)
                written.append(rel)
                if plots:
                    _plot_1d_csv(
                        folder / f"{stem}.csv",
                        plots_dir / f"{spec['plot_prefix']}_{gname}_{stem}.png",
                        shot=shot,
                        title=f"{spec['label']}: {stem}",
                        ylabel=stem,
                        window=window,
                        report=report,
                        run_dir=run_dir,
                    )

            # --- 2-D profiles ---
            y_coord = str(spec.get("y_coord") or "major_radius")
            for n in spec.get("vars_2d") or ():
                if n not in ds:
                    report.warnings.append(f"optional_var_missing:{gname}:{n}")
                    continue
                da = ds[n]
                df = _as_2d_long(da, y_coord=y_coord)
                if df is not None and not df.empty:
                    rel = _write_csv(df, folder / f"{n}_profile.csv", report, run_dir)
                    written.append(rel)
                if plots:
                    _plot_2d_da(
                        da,
                        plots_dir / f"{spec['plot_prefix']}_{gname}_{n}.png",
                        shot=shot,
                        title=f"{spec['label']}: {n}",
                        y_coord=y_coord,
                        window=window,
                        report=report,
                        run_dir=run_dir,
                    )

            if not written and not any(
                p.name.startswith(f"{spec['plot_prefix']}_{gname}")
                for p in plots_dir.glob("*.png")
                if plots_dir.is_dir()
            ):
                report.warnings.append(f"optional_group_empty_export:{gname}")

            entry["files"] = written
            entry["n_files"] = len(written)
            entry["path"] = _rel(run_dir, folder)
        except Exception as e:
            msg = f"optional_group_export_failed:{gname}:{type(e).__name__}:{e}"
            report.warnings.append(msg)
            entry["warning"] = msg
        finally:
            try:
                ds.close()
            except Exception:
                pass

        status["groups"][gname] = entry
        catalog["families"][f"diag_{gname}"] = entry

    # Sidecar status for UI
    status_path = measured_root / "00_index" / "optional_diagnostics.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    import json

    status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report.files_written.append(_rel(run_dir, status_path))
    catalog["optional_diagnostics"] = status
