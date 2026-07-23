"""ADR-002 FAIR-MAST EFIT++ compare + expert SHOT layout."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mast_freegsnke.config import AppConfig
from mast_freegsnke.efit_compare import (
    EfitCompareAuthority,
    EfitCompareError,
    load_efit_compare_authority,
    run_efit_compare,
    write_efit_compare_authority,
)
from mast_freegsnke.shot_layout import finalize_shot_layout, resolve_run_path


def test_shipped_efit_authority_validates() -> None:
    repo = Path(__file__).resolve().parents[1]
    auth = load_efit_compare_authority(repo / "configs" / "efit_compare_authority.json")
    assert auth.source == "fairmast_level2_equilibrium"
    assert auth.output_relpath == "04_efit_compare"


def test_authority_rejects_efit_ai_source() -> None:
    with pytest.raises(EfitCompareError, match="unsupported source"):
        EfitCompareAuthority(source="efit_ai_fortran").validate()


def test_default_config_compare_on() -> None:
    repo = Path(__file__).resolve().parents[1]
    cfg = AppConfig.load(repo / "configs" / "default.json")
    assert cfg.compare_efit_archive is True
    assert "equilibrium" in cfg.optional_groups
    assert cfg.efit_compare_authority_path


def test_config_requires_authority_when_compare_on(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    base = json.loads(
        (Path(__file__).resolve().parents[1] / "configs" / "default.json").read_text(
            encoding="utf-8"
        )
    )
    base["compare_efit_archive"] = True
    base["efit_compare_authority_path"] = None
    p.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="efit_compare_authority_path"):
        AppConfig.load(p)


def test_efit_compare_missing_cache_soft(tmp_path: Path) -> None:
    run_dir = tmp_path / "SHOT" / "1"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "inputs" / "window.json").write_text(
        json.dumps({"t_start": 0.2, "t_end": 0.4}), encoding="utf-8"
    )
    auth = load_efit_compare_authority(
        Path(__file__).resolve().parents[1] / "configs" / "efit_compare_authority.json"
    )
    rep = run_efit_compare(run_dir, shot=1, cache_dir=tmp_path / "empty_cache", auth=auth)
    assert rep.ok is False
    assert any("missing" in e.lower() for e in rep.errors)
    assert (run_dir / "04_efit_compare" / "COMPARE.json").exists()


def _write_mini_equilibrium_zarr(path: Path) -> None:
    xr = pytest.importorskip("xarray")
    pytest.importorskip("zarr")
    t = np.linspace(0.0, 1.0, 5)
    ds = xr.Dataset(
        {
            "elongation": ("time", np.linspace(1.5, 1.8, 5)),
            "q95": ("time", np.linspace(4.0, 5.0, 5)),
            "lcfs_r": (("time", "n"), np.tile(np.linspace(0.5, 1.2, 20), (5, 1))),
            "lcfs_z": (("time", "n"), np.tile(np.sin(np.linspace(0, 2 * np.pi, 20)), (5, 1))),
            "psi": (("time", "i", "j"), np.random.default_rng(0).normal(size=(5, 8, 8))),
        },
        coords={"time": t, "major_radius": np.linspace(0.2, 1.5, 8), "height": np.linspace(-1, 1, 8)},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(path, mode="w")


def test_efit_compare_with_synthetic_zarr(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    _write_mini_equilibrium_zarr(cache / "equilibrium.zarr")
    run_dir = tmp_path / "run"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "inputs" / "window.json").write_text(
        json.dumps({"t_start": 0.2, "t_end": 0.6}), encoding="utf-8"
    )
    auth = write_efit_compare_authority(
        run_dir / "inputs",
        load_efit_compare_authority(
            Path(__file__).resolve().parents[1] / "configs" / "efit_compare_authority.json"
        ),
    )
    auth_obj = load_efit_compare_authority(auth)
    rep = run_efit_compare(run_dir, shot=30201, cache_dir=cache, auth=auth_obj)
    assert rep.ok is True
    assert (run_dir / "04_efit_compare" / "efit_shape_timeseries.csv").exists()
    assert (run_dir / "04_efit_compare" / "efit_lcfs.csv").exists()
    assert (run_dir / "04_efit_compare" / "COMPARE.md").exists()


def test_finalize_shot_layout_moves(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    (run / "metrics").mkdir(parents=True)
    (run / "metrics" / "reconstruction_metrics.json").write_text("{}", encoding="utf-8")
    (run / "experimental_data" / "00_index").mkdir(parents=True)
    (run / "experimental_data" / "00_index" / "catalog.json").write_text("{}", encoding="utf-8")
    (run / "contracts").mkdir()
    (run / "contracts" / "x.json").write_text("{}", encoding="utf-8")
    (run / "inputs").mkdir()
    idx = finalize_shot_layout(run, shot=30201)
    assert (run / "03_reconstruction" / "metrics" / "reconstruction_metrics.json").exists()
    assert (run / "06_authorities" / "contracts" / "x.json").exists()
    assert (run / "00_START_HERE.txt").exists()
    assert resolve_run_path(run, "03_reconstruction/metrics", "metrics") is not None
    assert any(m["to"].startswith("03_reconstruction") for m in idx["moves"])
