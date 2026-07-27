"""Optional Level-2 diagnostic export (warn-only when missing)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from mast_freegsnke.experimental_data import ExperimentalDataReport, build_experimental_data
from mast_freegsnke.level2_diagnostics import OPTIONAL_DIAGNOSTIC_GROUPS, export_optional_diagnostics


def _seed_inputs(run_dir: Path) -> None:
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    t = [0.0, 0.1, 0.2]
    pd.DataFrame({"time": t, "ip": [1e5, 2e5, 8e5]}).to_csv(inputs / "ip.csv", index=False)
    (inputs / "window.json").write_text(
        json.dumps({"t_start": 0.05, "t_end": 0.18}) + "\n", encoding="utf-8"
    )


def _write_soft_x_zarr(path: Path) -> None:
    time = np.linspace(0.0, 0.3, 40)
    ch = np.arange(4)
    ds = xr.Dataset(
        {
            "horizontal_cam_lower": (("time", "channel"), np.random.default_rng(0).random((40, 4)) * 0.01),
            "horizontal_cam_upper": (("time", "channel"), np.random.default_rng(1).random((40, 4)) * 0.01),
            "tangential_cam": (("time", "channel"), np.random.default_rng(2).random((40, 4)) * 0.1),
        },
        coords={"time": time, "channel": ch},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(path, mode="w")


def _write_thomson_zarr(path: Path) -> None:
    time = np.linspace(0.0, 0.3, 30)
    r = np.linspace(0.2, 1.2, 12)
    rng = np.random.default_rng(3)
    ds = xr.Dataset(
        {
            "t_e": (("time", "major_radius"), rng.random((30, 12)) * 800),
            "n_e": (("time", "major_radius"), rng.random((30, 12)) * 1e19),
            "p_e": (("time", "major_radius"), rng.random((30, 12)) * 1e3),
            "t_e_core": ("time", rng.random(30) * 900),
            "n_e_core": ("time", rng.random(30) * 1e19),
        },
        coords={"time": time, "major_radius": r},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(path, mode="w")


def test_plot_2d_handles_transposed_dims(tmp_path: Path) -> None:
    """Thomson-like arrays with (R, time) dim order must not raise pcolormesh errors."""
    from mast_freegsnke.level2_diagnostics import _plot_2d_da

    time = np.linspace(0.0, 0.3, 80)
    r = np.linspace(0.2, 1.0, 40)
    # Deliberately transposed vs (time, R)
    da = xr.DataArray(
        np.random.default_rng(0).random((40, 80)),
        dims=("major_radius", "time"),
        coords={"major_radius": r, "time": time},
        name="t_e",
    )
    report = ExperimentalDataReport()
    out = tmp_path / "t_e.png"
    _plot_2d_da(
        da,
        out,
        shot=30201,
        title="t_e",
        y_coord="major_radius",
        window=(0.05, 0.25),
        report=report,
        run_dir=tmp_path,
    )
    assert out.is_file()
    assert out.stat().st_size > 1000
    assert not any("diag_plot_2d_failed" in w for w in report.warnings)

    assert "soft_x_rays" in OPTIONAL_DIAGNOSTIC_GROUPS
    assert "thomson_scattering" in OPTIONAL_DIAGNOSTIC_GROUPS
    assert "charge_exchange" in OPTIONAL_DIAGNOSTIC_GROUPS
    assert "summary" in OPTIONAL_DIAGNOSTIC_GROUPS


def test_export_optional_diagnostics_warns_when_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "SHOT" / "1"
    measured = run_dir / "02_measured_data"
    measured.mkdir(parents=True)
    cache = tmp_path / "data_cache" / "shot_1"
    cache.mkdir(parents=True)
    report = ExperimentalDataReport()
    catalog: dict = {"families": {}}
    export_optional_diagnostics(
        cache_dir=cache,
        measured_root=measured,
        run_dir=run_dir,
        shot=1,
        window=(0.0, 0.2),
        plots=False,
        report=report,
        catalog=catalog,
        groups=["soft_x_rays", "thomson_scattering"],
    )
    assert report.ok is True
    assert any("optional_group_missing:soft_x_rays" in w for w in report.warnings)
    assert any("optional_group_missing:thomson_scattering" in w for w in report.warnings)
    assert (measured / "09_soft_x_rays" / "MISSING.txt").exists()
    assert catalog["families"]["diag_soft_x_rays"]["available"] is False


def test_export_optional_diagnostics_writes_csv_and_plots(tmp_path: Path) -> None:
    run_dir = tmp_path / "SHOT" / "2"
    measured = run_dir / "02_measured_data"
    (measured / "05_plots").mkdir(parents=True)
    cache = tmp_path / "data_cache" / "shot_2"
    _write_soft_x_zarr(cache / "soft_x_rays.zarr")
    _write_thomson_zarr(cache / "thomson_scattering.zarr")
    report = ExperimentalDataReport()
    catalog: dict = {"families": {}}
    export_optional_diagnostics(
        cache_dir=cache,
        measured_root=measured,
        run_dir=run_dir,
        shot=2,
        window=(0.05, 0.2),
        plots=True,
        report=report,
        catalog=catalog,
        groups=["soft_x_rays", "thomson_scattering"],
    )
    assert catalog["families"]["diag_soft_x_rays"]["available"] is True
    assert (measured / "09_soft_x_rays" / "horizontal_cam_lower.csv").exists()
    assert (measured / "10_thomson_scattering" / "t_e_core.csv").exists()
    assert (measured / "10_thomson_scattering" / "t_e_profile.csv").exists()
    assert any("09_soft_x_rays" in p for p in report.plots_written) or list(
        (measured / "05_plots").glob("09_*.png")
    )
    assert (measured / "00_index" / "optional_diagnostics.json").exists()
    # No hard errors for optional path
    assert not report.errors


def test_build_experimental_data_integrates_optional(tmp_path: Path) -> None:
    run_dir = tmp_path / "SHOT" / "3"
    _seed_inputs(run_dir)
    cache = tmp_path / "data_cache" / "shot_3"
    _write_soft_x_zarr(cache / "soft_x_rays.zarr")
    rep = build_experimental_data(
        run_dir,
        shot=3,
        cache_dir=cache,
        machine_dir=None,
        repo_root=None,
        include_l1=False,
        include_l3=False,
        plots=False,
    )
    assert rep.ok, rep.errors
    cat = json.loads(
        (run_dir / "02_measured_data" / "00_index" / "catalog.json").read_text(encoding="utf-8")
    )
    assert cat["families"]["diag_soft_x_rays"]["available"] is True
    assert "optional_group_missing:thomson_scattering" in cat["warnings"]
