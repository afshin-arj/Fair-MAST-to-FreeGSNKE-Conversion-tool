"""ADR-004 Phase 1: profile trajectory authority + EFIT fit + evolutive consume hooks."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mast_freegsnke.config import AppConfig
from mast_freegsnke.efit_profile_fit import (
    ProfileFitError,
    build_profile_trajectory_from_efit,
    run_profile_trajectory_stage,
)
from mast_freegsnke.execution_authority import write_execution_authority
from mast_freegsnke.profile_trajectory import (
    ProfileKnot,
    ProfileTrajectory,
    interpolate_profile_at,
    load_profile_trajectory_policy,
    try_load_built_trajectory,
    write_profile_trajectory,
)


REPO = Path(__file__).resolve().parents[1]


def test_default_config_loads_profile_trajectory_flags() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.build_profile_trajectory is True
    assert cfg.profile_trajectory_authority_path == "configs/profile_trajectory_authority.json"
    assert "equilibrium" in cfg.optional_groups


def test_build_profile_trajectory_requires_path(tmp_path: Path) -> None:
    base = json.loads((REPO / "configs" / "default.json").read_text(encoding="utf-8"))
    base["build_profile_trajectory"] = True
    base["profile_trajectory_authority_path"] = None
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="profile_trajectory_authority_path"):
        AppConfig.load(p)


def test_policy_load_and_validate() -> None:
    pol = load_profile_trajectory_policy(REPO / "configs" / "profile_trajectory_authority.json")
    assert pol.enabled is True
    assert pol.require is False
    assert pol.fit_mode == "auto"
    assert pol.basis_type == "ConstrainPaxisIp"


def test_interpolate_linear() -> None:
    traj = ProfileTrajectory(
        authority_name="profile_trajectory",
        authority_version="1.0.0",
        basis_type="ConstrainPaxisIp",
        fit_mode_used="scalar_bridge",
        interpolation="linear",
        status="ok",
        knots=[
            ProfileKnot(0.0, 1000.0, 0.5, 1.8, 1.2),
            ProfileKnot(1.0, 2000.0, 0.5, 1.8, 1.2),
        ],
    )
    mid = interpolate_profile_at(traj, 0.5)
    assert mid["paxis"] == pytest.approx(1500.0)
    assert mid["alpha_m"] == pytest.approx(1.8)


def test_scalar_bridge_fit(tmp_path: Path) -> None:
    xr = pytest.importorskip("xarray")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write_execution_authority(inputs, metrics_n_times=5)
    (inputs / "window.json").write_text(
        json.dumps({"t_start": 0.1, "t_end": 0.5}), encoding="utf-8"
    )
    t = np.linspace(0.0, 0.6, 7)
    wmhd = 1e4 * (1.0 + 0.2 * np.sin(2 * np.pi * t / 0.6))
    ds = xr.Dataset({"wmhd": ("time", wmhd)}, coords={"time": t})
    cache = tmp_path / "cache"
    cache.mkdir()
    ds.to_zarr(cache / "equilibrium.zarr", mode="w")

    pol = load_profile_trajectory_policy(REPO / "configs" / "profile_trajectory_authority.json")
    from dataclasses import replace

    pol = replace(pol, fit_mode="scalar_bridge", n_knots=5, require=False)
    traj = build_profile_trajectory_from_efit(
        inputs_dir=inputs, cache_dir=cache, policy=pol, shot=30201
    )
    assert traj.status == "ok"
    assert traj.fit_mode_used == "scalar_bridge"
    assert len(traj.knots) == 5
    assert all(k.paxis_Pa > 0 for k in traj.knots)
    path = write_profile_trajectory(inputs, traj)
    assert path.exists()
    loaded = try_load_built_trajectory(inputs)
    assert loaded is not None
    assert loaded.content_sha256() == traj.content_sha256()


def test_archive_profiles_fit(tmp_path: Path) -> None:
    xr = pytest.importorskip("xarray")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write_execution_authority(inputs, metrics_n_times=4)
    (inputs / "window.json").write_text(
        json.dumps({"t_start": 0.0, "t_end": 1.0}), encoding="utf-8"
    )
    t = np.array([0.0, 0.5, 1.0])
    psi_n = np.linspace(0.0, 1.0, 21)
    # Synthetic ConstrainPaxisIp-like pprime
    am, an, paxis = 1.8, 1.2, 5e3
    shape = np.clip(1.0 - psi_n**am, 0.0, None) ** an
    pprime = np.stack([paxis * shape * (1.0 + 0.1 * i) for i in range(3)], axis=0)
    ds = xr.Dataset(
        {
            "pprime": (("time", "psi_n"), pprime),
            "wmhd": ("time", np.array([1e4, 1.1e4, 1.2e4])),
        },
        coords={"time": t, "psi_n": psi_n},
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    ds.to_zarr(cache / "equilibrium.zarr", mode="w")

    pol = load_profile_trajectory_policy(REPO / "configs" / "profile_trajectory_authority.json")
    from dataclasses import replace

    pol = replace(pol, fit_mode="archive_profiles", n_knots=3, require=True)
    traj = build_profile_trajectory_from_efit(
        inputs_dir=inputs, cache_dir=cache, policy=pol, shot=1
    )
    assert traj.status == "ok"
    assert traj.fit_mode_used == "archive_profiles"
    assert len(traj.knots) == 3
    # Recovered paxis should be in the same ballpark as synthetic
    assert traj.knots[0].paxis_Pa == pytest.approx(paxis, rel=0.35)


def test_insufficient_archive_soft_skip(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write_execution_authority(inputs, metrics_n_times=3)
    (inputs / "window.json").write_text(
        json.dumps({"t_start": 0.0, "t_end": 1.0}), encoding="utf-8"
    )
    pol = load_profile_trajectory_policy(REPO / "configs" / "profile_trajectory_authority.json")
    from dataclasses import replace

    pol = replace(pol, require=False)
    traj = build_profile_trajectory_from_efit(
        inputs_dir=inputs, cache_dir=tmp_path / "empty_cache", policy=pol, shot=1
    )
    assert traj.status == "skipped_insufficient_archive"
    assert try_load_built_trajectory(inputs) is None
    write_profile_trajectory(inputs, traj)
    assert try_load_built_trajectory(inputs) is None  # status not ok


def test_require_true_blocks(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write_execution_authority(inputs, metrics_n_times=3)
    (inputs / "window.json").write_text(
        json.dumps({"t_start": 0.0, "t_end": 1.0}), encoding="utf-8"
    )
    pol = load_profile_trajectory_policy(REPO / "configs" / "profile_trajectory_authority.json")
    from dataclasses import replace

    pol = replace(pol, require=True)
    with pytest.raises(ProfileFitError):
        build_profile_trajectory_from_efit(
            inputs_dir=inputs, cache_dir=tmp_path / "empty", policy=pol, shot=1
        )


def test_stage_report_ok(tmp_path: Path) -> None:
    xr = pytest.importorskip("xarray")
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write_execution_authority(inputs, metrics_n_times=4)
    (inputs / "window.json").write_text(
        json.dumps({"t_start": 0.2, "t_end": 0.8}), encoding="utf-8"
    )
    t = np.linspace(0.0, 1.0, 11)
    ds = xr.Dataset({"wmhd": ("time", 2e4 + 1e3 * t)}, coords={"time": t})
    cache = tmp_path / "cache"
    cache.mkdir()
    ds.to_zarr(cache / "equilibrium.zarr", mode="w")
    rep = run_profile_trajectory_stage(
        inputs_dir=inputs,
        cache_dir=cache,
        policy_path=REPO / "configs" / "profile_trajectory_authority.json",
        shot=30202,
    )
    assert rep["ok"] is True
    assert rep["n_knots"] >= 2
    assert (inputs / "profile_trajectory_authority" / "profile_trajectory.json").exists()
    assert (inputs / "profile_trajectory_authority" / "profile_trajectory_authority.json").exists()


def test_coil_limits_measured_peak_margin_shipped() -> None:
    obj = json.loads((REPO / "configs" / "coil_limits_authority.json").read_text(encoding="utf-8"))
    assert obj["status"] == "cited"
    assert obj["limit_policy"] == "measured_peak_margin"
    assert float(obj["margin_factor"]) == 1.2
    assert obj["circuits"] == {}
    assert obj.get("citation")

def test_evolutive_template_mentions_trajectory() -> None:
    tpl = (REPO / "templates" / "evolutive_run.py.tpl").read_text(encoding="utf-8")
    assert "profile_trajectory" in tpl
    assert "overrides scale_paxis_with_ip" in tpl
    assert "try_load_built_trajectory" in tpl


def test_adr004_exists() -> None:
    p = REPO / "docs" / "adr" / "004-profile-trajectory-and-planner.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "Phase 2" in text
    assert "coil_limits_authority" in text
    assert "MATLAB" in text or "GSPulse" in text
