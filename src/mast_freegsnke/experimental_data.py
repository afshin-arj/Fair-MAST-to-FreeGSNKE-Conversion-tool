"""Categorized experimental FAIR-MAST data pack under SHOT/<N>/experimental_data/.

Portable (pathlib, matplotlib Agg, no display, no drive-letter assumptions).
Shot-only: enabled from config with no new interactive prompts.
Never invents calibrations, units, or missing Level-1/3 channels.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
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


_SUBDIRS = (
    "00_index",
    "01_plasma",
    "02_pf",
    "03_magnetics",
    "04_geometry",
    "05_plots",
    "l1",
    "l3",
)


@dataclass
class ExperimentalDataReport:
    ok: bool = True
    root: str = ""
    files_written: List[str] = field(default_factory=list)
    plots_written: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    catalog: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "root": self.root,
            "files_written": list(self.files_written),
            "plots_written": list(self.plots_written),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "n_files": len(self.files_written),
            "n_plots": len(self.plots_written),
            "catalog_path": "experimental_data/00_index/catalog.json",
        }


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_csv(
    src: Path,
    dst: Path,
    *,
    report: ExperimentalDataReport,
    root: Path,
    catalog_entry: Dict[str, Any],
) -> bool:
    if not src.exists():
        report.warnings.append(f"missing_source:{src.name}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    report.files_written.append(_rel(root, dst))
    catalog_entry["path"] = _rel(root, dst)
    catalog_entry["source_inputs"] = src.name
    try:
        df = pd.read_csv(dst, nrows=5)
        catalog_entry["columns"] = [str(c) for c in df.columns]
        catalog_entry["n_columns"] = int(len(df.columns))
        # Full row count (cheap for typical magnetics sizes)
        n = sum(1 for _ in open(dst, "r", encoding="utf-8", errors="replace")) - 1
        catalog_entry["n_rows_approx"] = max(0, int(n))
    except Exception as e:
        report.warnings.append(f"csv_meta_failed:{dst.name}:{type(e).__name__}")
    return True


def _load_window(inputs: Path) -> Optional[Tuple[float, float]]:
    wp = inputs / "window.json"
    if not wp.exists():
        return None
    try:
        obj = json.loads(wp.read_text(encoding="utf-8"))
        if isinstance(obj, dict) and "t_start" in obj and "t_end" in obj:
            return float(obj["t_start"]), float(obj["t_end"])
    except Exception:
        return None
    return None


def _shade_window(ax: Any, window: Optional[Tuple[float, float]]) -> None:
    if window is None:
        return
    t0, t1 = window
    ax.axvspan(t0, t1, color="0.85", zorder=0, label="formed-plasma window")


def _style_axes(ax: Any, *, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best", fontsize=8, frameon=False)


def _save_fig(fig: Any, path: Path, report: ExperimentalDataReport, root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    report.plots_written.append(_rel(root, path))


def _plot_timeseries_csv(
    csv_path: Path,
    out_png: Path,
    *,
    shot: int,
    title: str,
    ylabel: str,
    window: Optional[Tuple[float, float]],
    columns: Optional[Sequence[str]] = None,
    max_series: int = 12,
    report: ExperimentalDataReport,
    root: Path,
    watermark: Optional[str] = None,
) -> None:
    if not _HAS_MPL or not csv_path.exists():
        return
    df = pd.read_csv(csv_path)
    if "time" not in df.columns:
        report.warnings.append(f"plot_skip_no_time:{csv_path.name}")
        return
    t = df["time"].to_numpy(dtype=float)
    cols = list(columns) if columns is not None else [c for c in df.columns if c != "time"]
    usable: List[str] = []
    for c in cols:
        y = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        if np.isfinite(y).sum() >= 2:
            usable.append(c)
        if len(usable) >= max_series:
            break
    if not usable:
        report.warnings.append(f"plot_skip_no_finite:{csv_path.name}")
        return
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    _shade_window(ax, window)
    for c in usable:
        y = pd.to_numeric(df[c], errors="coerce").to_numpy(dtype=float)
        ax.plot(t, y, lw=1.1, label=str(c))
    _style_axes(ax, title=f"Shot {shot}: {title}", xlabel="time (s)", ylabel=ylabel)
    if watermark:
        ax.text(
            0.99,
            0.02,
            watermark,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=8,
            color="0.35",
            style="italic",
        )
    n_extra = len(cols) - len(usable)
    if n_extra > 0:
        ax.text(
            0.01,
            0.98,
            f"showing {len(usable)}/{len(cols)} channels",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=8,
            color="0.4",
        )
    _save_fig(fig, out_png, report, root)


def _export_limiter_from_cache(
    cache_dir: Optional[Path],
    dst: Path,
    report: ExperimentalDataReport,
    root: Path,
) -> Optional[Dict[str, Any]]:
    if cache_dir is None:
        return None
    wall = cache_dir / "wall.zarr"
    if not wall.exists():
        report.warnings.append("limiter_skip:wall.zarr_missing")
        return None
    try:
        import zarr  # type: ignore

        g = zarr.open_group(str(wall), mode="r")
        if "limiter_r" not in g or "limiter_z" not in g:
            report.warnings.append("limiter_skip:missing_limiter_rz")
            return None
        r = np.asarray(g["limiter_r"][:], dtype=float).ravel()
        z = np.asarray(g["limiter_z"][:], dtype=float).ravel()
        m = np.isfinite(r) & np.isfinite(z)
        df = pd.DataFrame({"R_m": r[m], "Z_m": z[m]})
        dst.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(dst, index=False)
        report.files_written.append(_rel(root, dst))
        return {
            "path": _rel(root, dst),
            "source": "wall.zarr limiter_r/z",
            "level": "L2",
            "units": {"R_m": "m", "Z_m": "m"},
            "n_points": int(len(df)),
            "note": "EFIT limiter geometry — not CAD vessel survey",
        }
    except Exception as e:
        report.warnings.append(f"limiter_export_failed:{type(e).__name__}:{e}")
        return None


def _plot_machine_rz(
    geom_dir: Path,
    plots_dir: Path,
    *,
    shot: int,
    machine_dir: Optional[Path],
    report: ExperimentalDataReport,
    root: Path,
) -> None:
    if not _HAS_MPL:
        return
    lim = geom_dir / "limiter_rz.csv"
    coil_json = None
    if machine_dir is not None:
        cand = machine_dir / "coil_geometry.json"
        if cand.exists():
            coil_json = cand
    fig, ax = plt.subplots(figsize=(5.2, 8.0))
    if lim.exists():
        df = pd.read_csv(lim)
        if {"R_m", "Z_m"}.issubset(df.columns):
            ax.plot(df["R_m"], df["Z_m"], "k-", lw=1.4, label="EFIT limiter")
    if coil_json is not None:
        try:
            obj = json.loads(coil_json.read_text(encoding="utf-8"))
            # Support either list of coils or dict keyed by name
            items: List[Tuple[str, Any]] = []
            if isinstance(obj, dict):
                if "coils" in obj and isinstance(obj["coils"], list):
                    for c in obj["coils"]:
                        if isinstance(c, dict):
                            items.append((str(c.get("name", "coil")), c))
                else:
                    for k, v in obj.items():
                        if isinstance(v, dict) and ("R" in v or "r" in v or "filaments" in v):
                            items.append((str(k), v))
            for name, c in items[:40]:
                # Best-effort rectangles / points from heterogeneous schemas
                if "filaments" in c and isinstance(c["filaments"], list):
                    rs = [float(f.get("R", f.get("r", np.nan))) for f in c["filaments"]]
                    zs = [float(f.get("Z", f.get("z", np.nan))) for f in c["filaments"]]
                    ax.scatter(rs, zs, s=6, label=name if len(items) <= 12 else None)
                elif "R" in c and "Z" in c:
                    ax.plot(float(c["R"]), float(c["Z"]), "o", ms=4, label=name if len(items) <= 12 else None)
        except Exception as e:
            report.warnings.append(f"machine_plot_coil_json:{type(e).__name__}")
    ax.set_aspect("equal")
    ax.set_xlabel("R (m)")
    ax.set_ylabel("Z (m)")
    ax.set_title(f"Shot {shot}: machine geometry (L2)")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best", fontsize=7, frameon=False)
    ax.text(
        0.98,
        0.02,
        "limiter = EFIT (not CAD)",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=8,
        color="0.4",
        style="italic",
    )
    _save_fig(fig, plots_dir / "04_machine_rz.png", report, root)


def _write_readme(path: Path, shot: int) -> None:
    path.write_text(
        "\n".join(
            [
                f"experimental_data — shot {shot}",
                "=" * 40,
                "",
                "Professionally categorized FAIR-MAST experimental traces and plots.",
                "Sibling to inputs/ (tooling) and synthetic/ (FreeGSNKE).",
                "",
                "Folders:",
                "  00_index/      catalog.json + this README",
                "  01_plasma/    Ip",
                "  02_pf/        PF currents/voltages (raw + mapped)",
                "  03_magnetics/ flux loops, pickups, audit_* (uncalibrated)",
                "  04_geometry/  limiter / geometry exports",
                "  05_plots/     PNG figures (matplotlib Agg — headless portable)",
                "  l1/           Level-1 inventory / optional exports",
                "  l3/           Level-3 status (not wired in pipeline)",
                "",
                "Rules: measured vs derived are labeled in catalog.json.",
                "Never invent V→T calibrations, resistivity, or missing PF voltages.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def build_experimental_data(
    run_dir: Path,
    *,
    shot: int,
    cache_dir: Optional[Path] = None,
    machine_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    include_l1: bool = True,
    include_l3: bool = True,
    plots: bool = True,
) -> ExperimentalDataReport:
    """Build SHOT/<N>/experimental_data from existing extract + authorities.

    Non-blocking by design: returns ok=False with errors/warnings rather than raising
    for missing optional families. Portable across Windows/POSIX lab machines.
    """
    run_dir = Path(run_dir)
    inputs = run_dir / "inputs"
    root = run_dir / "experimental_data"
    report = ExperimentalDataReport(root=_rel(run_dir, root) if root.exists() or True else "experimental_data")
    report.root = "experimental_data"

    if not inputs.exists():
        report.ok = False
        report.errors.append("inputs_dir_missing")
        return report

    for sub in _SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)

    _write_readme(root / "00_index" / "README.txt", shot)
    report.files_written.append("experimental_data/00_index/README.txt")

    window = _load_window(inputs)
    catalog: Dict[str, Any] = {
        "shot": int(shot),
        "schema_version": "1.0",
        "level_policy": {
            "L2": "production — exported from FAIR-MAST Level-2 extract",
            "L1": "opt-in inventory / cached artifacts only (no invented channels)",
            "L3": "not wired — status only until public groups + authority exist",
        },
        "window_s": {"t_start": window[0], "t_end": window[1]} if window else None,
        "families": {},
    }

    # --- 01 plasma ---
    fam: Dict[str, Any] = {
        "level": "L2",
        "kind": "measured",
        "units": {"ip": "A"},
        "timebase": "magnetics.time",
    }
    if _copy_csv(inputs / "ip.csv", root / "01_plasma" / "ip.csv", report=report, root=run_dir, catalog_entry=fam):
        catalog["families"]["plasma_ip"] = fam

    # --- 02 PF ---
    for src_name, dst_name, meta in [
        (
            "pf_active_raw.csv",
            "currents_raw.csv",
            {
                "level": "L2",
                "kind": "measured",
                "units_note": "A from pf_active.coil_current attrs",
                "timebase": "pf_active",
            },
        ),
        (
            "pf_currents.csv",
            "currents_circuits.csv",
            {
                "level": "L2",
                "kind": "derived",
                "derivation": "configs/coil_map.json (mean series; antisym_mean P6)",
                "units_note": "A circuit amp for FreeGSNKE",
            },
        ),
        (
            "pf_voltages_raw.csv",
            "voltages_raw.csv",
            {
                "level": "L2",
                "kind": "measured",
                "units_note": "V (p1,p2,p4,p5)",
            },
        ),
        (
            "pf_voltages.csv",
            "voltages_circuits.csv",
            {
                "level": "L2",
                "kind": "derived",
                "derivation": "voltage_map (+ from_current_ohmic for P3/P6)",
                "units_note": "V",
            },
        ),
    ]:
        entry = dict(meta)
        if _copy_csv(inputs / src_name, root / "02_pf" / dst_name, report=report, root=run_dir, catalog_entry=entry):
            catalog["families"][dst_name.replace(".csv", "")] = entry

    # --- 03 magnetics ---
    for src_name, dst_name, meta in [
        (
            "flux_loops.csv",
            "flux_loops.csv",
            {"level": "L2", "kind": "measured", "units_note": "Wb"},
        ),
        (
            "pickups.csv",
            "pickups.csv",
            {"level": "L2", "kind": "measured", "units_note": "T (CCBV/OBV/OBR)"},
        ),
    ]:
        entry = dict(meta)
        if _copy_csv(
            inputs / src_name,
            root / "03_magnetics" / dst_name,
            report=report,
            root=run_dir,
            catalog_entry=entry,
        ):
            catalog["families"][dst_name.replace(".csv", "")] = entry

    audit_src = inputs / "audit_other_timebase"
    audit_dst = root / "03_magnetics" / "audit_other_timebase"
    if audit_src.is_dir():
        audit_dst.mkdir(parents=True, exist_ok=True)
        n_audit = 0
        for p in sorted(audit_src.glob("*.csv")):
            shutil.copy2(p, audit_dst / p.name)
            report.files_written.append(_rel(run_dir, audit_dst / p.name))
            n_audit += 1
        catalog["families"]["audit_other_timebase"] = {
            "level": "L2",
            "kind": "audit_uncalibrated",
            "n_files": n_audit,
            "path": _rel(run_dir, audit_dst),
            "watermark": "uncalibrated — awaiting diagnostic_calibration authority",
        }

    # --- 04 geometry ---
    lim_meta = _export_limiter_from_cache(
        Path(cache_dir) if cache_dir else None,
        root / "04_geometry" / "limiter_rz.csv",
        report,
        run_dir,
    )
    if lim_meta:
        catalog["families"]["limiter_rz"] = lim_meta

    if machine_dir is not None:
        md = Path(machine_dir)
        for name in ("coil_geometry.json", "probe_geometry.json", "FREEGSNKE_MACHINE_PROVENANCE.json"):
            src = md / name
            if src.exists():
                dst = root / "04_geometry" / name
                shutil.copy2(src, dst)
                report.files_written.append(_rel(run_dir, dst))
                catalog["families"][name.replace(".json", "")] = {
                    "level": "authority",
                    "kind": "geometry_snapshot",
                    "path": _rel(run_dir, dst),
                    "source": str(src).replace("\\", "/"),
                }

    # --- L1 ---
    l1_dir = root / "l1"
    l1_status: Dict[str, Any] = {
        "included": bool(include_l1),
        "pipeline_downloads_l1": False,
        "note": (
            "Level-1 is not part of the default download path. "
            "This folder holds inventory evidence and any locally cached L1 artifacts."
        ),
    }
    if include_l1:
        inv = None
        if repo_root is not None:
            cand = Path(repo_root) / "configs" / "l1_voltage_inventory_30201.json"
            if cand.exists():
                inv = cand
        # Also accept inventory next to run if copied
        if inv is None:
            for cand in (
                run_dir / "contracts" / "l1_voltage_inventory_30201.json",
                Path("configs") / "l1_voltage_inventory_30201.json",
            ):
                if cand.exists():
                    inv = cand
                    break
        if inv is not None:
            dst = l1_dir / "l1_voltage_inventory_30201.json"
            shutil.copy2(inv, dst)
            report.files_written.append(_rel(run_dir, dst))
            l1_status["inventory_copied"] = _rel(run_dir, dst)
        if cache_dir is not None:
            cd = Path(cache_dir)
            cached = sorted(
                [p.name for p in cd.iterdir() if p.name.lower().startswith("l1")]
            ) if cd.exists() else []
            l1_status["cache_l1_artifacts"] = cached
            # Copy small JSON sidecars if present
            for p in cd.glob("l1_*.json") if cd.exists() else []:
                dst = l1_dir / p.name
                shutil.copy2(p, dst)
                report.files_written.append(_rel(run_dir, dst))
        (l1_dir / "README.txt").write_text(
            "\n".join(
                [
                    "Level-1 (optional)",
                    "------------------",
                    "Public L1 groups are not auto-downloaded by mast-freegsnke.",
                    "See l1_voltage_inventory_*.json for P3/P6 voltage evidence.",
                    "Do not treat xma/p6_volts as FreeGSNKE PF drive without calibration authority.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        report.files_written.append("experimental_data/l1/README.txt")
    else:
        (l1_dir / "SKIPPED.txt").write_text(
            "experimental_data_include_l1=false\n", encoding="utf-8"
        )
    catalog["families"]["l1"] = l1_status
    _write_json(l1_dir / "STATUS.json", l1_status)
    report.files_written.append("experimental_data/l1/STATUS.json")

    # --- L3 ---
    l3_dir = root / "l3"
    l3_status = {
        "included": bool(include_l3),
        "wired": False,
        "note": (
            "FAIR-MAST Level-3 products are not wired in this pipeline. "
            "No CSV/plot is fabricated. Enable only after public groups exist "
            "and an authority JSON is declared."
        ),
    }
    if include_l3:
        (l3_dir / "README.txt").write_text(
            "\n".join(
                [
                    "Level-3 (not wired)",
                    "-------------------",
                    "No level3_s3_prefix / extractor in mast-freegsnke yet.",
                    "Future: EFIT/profiles CSV under this folder with declared authority.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        report.files_written.append("experimental_data/l3/README.txt")
    else:
        (l3_dir / "SKIPPED.txt").write_text(
            "experimental_data_include_l3=false\n", encoding="utf-8"
        )
    catalog["families"]["l3"] = l3_status
    _write_json(l3_dir / "STATUS.json", l3_status)
    report.files_written.append("experimental_data/l3/STATUS.json")

    # --- plots ---
    plots_dir = root / "05_plots"
    if plots:
        if not _HAS_MPL:
            report.warnings.append("matplotlib_unavailable:plots_skipped")
        else:
            try:
                _plot_timeseries_csv(
                    root / "01_plasma" / "ip.csv",
                    plots_dir / "01_plasma_ip.png",
                    shot=shot,
                    title="plasma current (L2 measured)",
                    ylabel="Ip (A)",
                    window=window,
                    report=report,
                    root=run_dir,
                )
                _plot_timeseries_csv(
                    root / "02_pf" / "currents_raw.csv",
                    plots_dir / "02_pf_currents_raw.png",
                    shot=shot,
                    title="PF currents raw FEED (L2 measured)",
                    ylabel="I (A)",
                    window=window,
                    max_series=10,
                    report=report,
                    root=run_dir,
                )
                _plot_timeseries_csv(
                    root / "02_pf" / "currents_circuits.csv",
                    plots_dir / "02_pf_currents_circuits.png",
                    shot=shot,
                    title="PF currents mapped circuits (derived coil_map)",
                    ylabel="I (A)",
                    window=window,
                    report=report,
                    root=run_dir,
                    watermark="derived: coil_map",
                )
                _plot_timeseries_csv(
                    root / "02_pf" / "voltages_raw.csv",
                    plots_dir / "02_pf_voltages_raw.png",
                    shot=shot,
                    title="PF voltages measured (L2 p1/p2/p4/p5)",
                    ylabel="V (V)",
                    window=window,
                    report=report,
                    root=run_dir,
                )
                _plot_timeseries_csv(
                    root / "02_pf" / "voltages_circuits.csv",
                    plots_dir / "02_pf_voltages_circuits.png",
                    shot=shot,
                    title="PF voltages circuit vector (derived voltage_map)",
                    ylabel="V (V)",
                    window=window,
                    report=report,
                    root=run_dir,
                    watermark="derived: voltage_map / I×R",
                )
                _plot_timeseries_csv(
                    root / "03_magnetics" / "flux_loops.csv",
                    plots_dir / "03_flux_loops.png",
                    shot=shot,
                    title="flux loops (L2 measured)",
                    ylabel="ψ (Wb)",
                    window=window,
                    max_series=10,
                    report=report,
                    root=run_dir,
                )
                pick = root / "03_magnetics" / "pickups.csv"
                if pick.exists():
                    cols = [c for c in pd.read_csv(pick, nrows=0).columns if c != "time"]
                    ccbv = [c for c in cols if str(c).upper().startswith("CCBV")][:10]
                    obv = [c for c in cols if str(c).upper().startswith("OBV")][:10]
                    obr = [c for c in cols if str(c).upper().startswith("OBR")][:10]
                    if ccbv:
                        _plot_timeseries_csv(
                            pick,
                            plots_dir / "03_pickups_ccbv.png",
                            shot=shot,
                            title="pickups CCBV (L2 measured)",
                            ylabel="B (T)",
                            window=window,
                            columns=ccbv,
                            report=report,
                            root=run_dir,
                        )
                    if obv:
                        _plot_timeseries_csv(
                            pick,
                            plots_dir / "03_pickups_obv.png",
                            shot=shot,
                            title="pickups OBV (L2 measured)",
                            ylabel="B (T)",
                            window=window,
                            columns=obv,
                            report=report,
                            root=run_dir,
                        )
                    if obr:
                        _plot_timeseries_csv(
                            pick,
                            plots_dir / "03_pickups_obr.png",
                            shot=shot,
                            title="pickups OBR (L2 measured)",
                            ylabel="B (T)",
                            window=window,
                            columns=obr,
                            report=report,
                            root=run_dir,
                        )
                # Audit watermark plots (first CSV only if present)
                audit_dir = root / "03_magnetics" / "audit_other_timebase"
                if audit_dir.is_dir():
                    audits = sorted(audit_dir.glob("*.csv"))
                    for ap in audits[:3]:
                        _plot_timeseries_csv(
                            ap,
                            plots_dir / f"03_audit_{ap.stem[:40]}.png",
                            shot=shot,
                            title=f"audit {ap.stem} (uncalibrated)",
                            ylabel="raw (see catalog)",
                            window=None,
                            max_series=8,
                            report=report,
                            root=run_dir,
                            watermark="AUDIT — uncalibrated",
                        )
                _plot_machine_rz(
                    root / "04_geometry",
                    plots_dir,
                    shot=shot,
                    machine_dir=Path(machine_dir) if machine_dir else None,
                    report=report,
                    root=run_dir,
                )
            except Exception as e:
                report.warnings.append(f"plots_failed:{type(e).__name__}:{e}")

    catalog["plots"] = list(report.plots_written)
    catalog["warnings"] = list(report.warnings)
    cat_path = root / "00_index" / "catalog.json"
    _write_json(cat_path, catalog)
    report.files_written.append("experimental_data/00_index/catalog.json")
    report.catalog = catalog

    # Core L2 families expected after a normal extract
    required_ok = (root / "01_plasma" / "ip.csv").exists()
    if not required_ok:
        report.ok = False
        report.errors.append("core_ip_missing")
    report.root = "experimental_data"
    return report
