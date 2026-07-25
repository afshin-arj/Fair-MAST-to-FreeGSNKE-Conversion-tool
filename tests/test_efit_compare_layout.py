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
    assert auth.compare_mode == "both"
    assert auth.enable_forward_replay is True


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
    th = np.linspace(0, 2 * np.pi, 20)
    lcfs_r = np.tile(0.9 + 0.3 * np.cos(th), (5, 1))
    lcfs_z = np.tile(0.35 * np.sin(th), (5, 1))
    ds = xr.Dataset(
        {
            "elongation": ("time", np.linspace(1.5, 1.8, 5)),
            "q95": ("time", np.linspace(4.0, 5.0, 5)),
            "magnetic_axis_r": ("time", np.full(5, 0.9)),
            "magnetic_axis_z": ("time", np.zeros(5)),
            "x_point_r": ("time", np.full(5, 0.7)),
            "x_point_z": ("time", np.full(5, -0.8)),
            "minor_radius": ("time", np.full(5, 0.55)),
            "lcfs_r": (("time", "n"), lcfs_r),
            "lcfs_z": (("time", "n"), lcfs_z),
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
    pd = pytest.importorskip("pandas")
    (run_dir / "presentation").mkdir(parents=True, exist_ok=True)
    theta = np.linspace(0, 2 * np.pi, 40)
    pd.DataFrame(
        {"R": 0.85 + 0.35 * np.cos(theta), "Z": 0.4 * np.sin(theta)}
    ).to_csv(run_dir / "presentation" / "freegsnke_lcfs.csv", index=False)
    auth = write_efit_compare_authority(
        run_dir / "inputs",
        load_efit_compare_authority(
            Path(__file__).resolve().parents[1] / "configs" / "efit_compare_authority.json"
        ),
    )
    auth_obj = load_efit_compare_authority(auth)
    assert auth_obj.compare_mode == "both"
    assert auth_obj.psi_convention == "Wb_per_2pi"
    rep = run_efit_compare(run_dir, shot=30201, cache_dir=cache, auth=auth_obj)
    assert rep.ok is True
    assert (run_dir / "04_efit_compare" / "efit_shape_timeseries.csv").exists()
    assert (run_dir / "04_efit_compare" / "efit_lcfs.csv").exists()
    assert (run_dir / "04_efit_compare" / "COMPARE.md").exists()
    assert (run_dir / "04_efit_compare" / "shape_scorecard.csv").exists()
    sc = json.loads((run_dir / "04_efit_compare" / "shape_scorecard.json").read_text(encoding="utf-8"))
    assert sc["psi_convention"] == "Wb_per_2pi"
    assert sc["compare_mode"] == "reconstruction_vs_archive"
    assert any(r["quantity"] == "R_in_midplane" for r in sc["rows"])
    assert any(r["quantity"] == "lcfs_mean_nn_symmetric" for r in sc["rows"])
    rin = next(r for r in sc["rows"] if r["quantity"] == "R_in_midplane")
    assert rin["freegsnke"] is not None  # midplane from LCFS without eq object
    assert rep.time_align_note
    assert (run_dir / "04_efit_compare" / "efit_snapshot.json").exists()


def test_midplane_and_lcfs_distance_helpers() -> None:
    from mast_freegsnke.shape_scorecard import midplane_radii, polyline_mean_nearest_distance_m

    th = np.linspace(0, 2 * np.pi, 60)
    r = 1.0 + 0.4 * np.cos(th)
    z = 0.5 * np.sin(th)
    mid = midplane_radii(r, z, z_ref=0.0, z_tol=0.08)
    assert mid["R_in_m"] is not None and mid["R_out_m"] is not None
    assert mid["R_out_m"] > mid["R_in_m"]
    d = polyline_mean_nearest_distance_m(r, z, r * 1.01, z)
    assert d["mean_nn_symmetric_m"] is not None
    assert d["mean_nn_symmetric_m"] > 0.0


def test_psi_pack_prefers_total_psi_over_plasma() -> None:
    from mast_freegsnke.freegsnke_lcfs import psi_pack_from_dump

    R = np.linspace(0.2, 1.5, 8)
    Z = np.linspace(-1, 1, 10)
    plasma = np.ones((10, 8))
    total = np.full((10, 8), 2.0)
    pack = psi_pack_from_dump(
        {
            "plasma_psi": plasma,
            "total_psi": total,
            "grid": {"R": R, "Z": Z},
            "t0": 0.25,
        }
    )
    assert pack is not None
    assert pack["kind"] == "total_psi"
    assert pack["comparable_to_efit_total_psi"] is True
    assert float(pack["psi"][0, 0]) == 2.0
    plasma_only = psi_pack_from_dump(
        {"plasma_psi": plasma, "grid": {"R": R, "Z": Z}, "t0": 0.25}
    )
    assert plasma_only is not None
    assert plasma_only["kind"] == "plasma_psi"
    assert plasma_only["comparable_to_efit_total_psi"] is False


def test_lcfs_candidate_order_prefers_presentation(tmp_path: Path) -> None:
    from mast_freegsnke.freegsnke_lcfs import freegsnke_lcfs_csv_candidates

    run = tmp_path / "shot"
    cands = freegsnke_lcfs_csv_candidates(run)
    assert cands[0].name == "freegsnke_forward_replay_lcfs.csv"
    assert any(p.name == "freegsnke_lcfs.csv" and "presentation" in str(p).replace("\\", "/") for p in cands)


def test_scorecard_aligns_efit_to_freegsnke_t0(tmp_path: Path) -> None:
    """Single-time FreeGSNKE LCFS must not be scored against window-mid EFIT."""
    cache = tmp_path / "cache"
    _write_mini_equilibrium_zarr(cache / "equilibrium.zarr")
    run_dir = tmp_path / "run"
    (run_dir / "inputs").mkdir(parents=True)
    # Window mid ≈ 0.4; FreeGSNKE solve at t0=0.1
    (run_dir / "inputs" / "window.json").write_text(
        json.dumps({"t_start": 0.0, "t_end": 0.8}), encoding="utf-8"
    )
    pd = pytest.importorskip("pandas")
    (run_dir / "presentation").mkdir(parents=True, exist_ok=True)
    theta = np.linspace(0, 2 * np.pi, 40)
    pd.DataFrame(
        {
            "R": 0.85 + 0.35 * np.cos(theta),
            "Z": 0.4 * np.sin(theta),
            "time": np.full(40, 0.1),
        }
    ).to_csv(run_dir / "presentation" / "freegsnke_lcfs.csv", index=False)
    import pickle

    R = np.linspace(0.2, 1.5, 8)
    Z = np.linspace(-1, 1, 10)
    with open(run_dir / "inverse_dump.pkl", "wb") as f:
        pickle.dump(
            {
                "t0": 0.1,
                "plasma_psi": np.ones((10, 8)),
                "grid": {"R": R, "Z": Z, "nx": 8, "ny": 10},
                "lcfs_R": 0.85 + 0.35 * np.cos(theta),
                "lcfs_Z": 0.4 * np.sin(theta),
            },
            f,
        )
    auth_obj = load_efit_compare_authority(
        Path(__file__).resolve().parents[1] / "configs" / "efit_compare_authority.json"
    )
    rep = run_efit_compare(run_dir, shot=30201, cache_dir=cache, auth=auth_obj)
    assert rep.ok is True
    assert rep.t_freegsnke == pytest.approx(0.1)
    assert rep.t_efit == pytest.approx(0.0) or abs(float(rep.t_efit) - 0.1) <= 0.25
    assert "scorecard_efit_nearest_to_freegsnke_t0" in (rep.time_align_note or "")


def test_forward_replay_scorecard_uses_matched_drive(tmp_path: Path) -> None:
    """Scorecard prefers forward_replay LCFS when GS succeeds with mocked solver."""
    from mast_freegsnke.efit_forward_replay import run_efit_forward_replay
    from mast_freegsnke.execution_authority import write_execution_authority
    from mast_freegsnke.profile_trajectory import (
        ProfileKnot,
        ProfileTrajectory,
        write_profile_trajectory,
    )

    run = tmp_path / "run"
    inputs = run / "inputs"
    inputs.mkdir(parents=True)
    write_execution_authority(inputs, metrics_n_times=5)
    traj = ProfileTrajectory(
        authority_name="profile_trajectory",
        authority_version="1.0.0",
        status="ok",
        fit_mode_used="scalar_bridge",
        basis_type="ConstrainPaxisIp",
        interpolation="linear",
        knots=[
            ProfileKnot(t_s=0.2, paxis_Pa=8e3, fvac=0.5, alpha_m=1.8, alpha_n=1.2),
            ProfileKnot(t_s=0.4, paxis_Pa=9e3, fvac=0.5, alpha_m=1.8, alpha_n=1.2),
        ],
    )
    write_profile_trajectory(inputs, traj)
    pd = pytest.importorskip("pandas")
    circuits = ["P2_inner", "P2_outer", "P3", "P4", "P5", "P6", "Solenoid"]
    rows = {"time": [0.2, 0.3, 0.4]}
    for c in circuits:
        rows[c] = [1e3, 1.1e3, 1.2e3]
    pd.DataFrame(rows).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame({"time": [0.2, 0.3, 0.4], "Ip": [6e5, 6.1e5, 6.2e5]}).to_csv(
        inputs / "ip.csv", index=False
    )
    machine = tmp_path / "machine"
    machine.mkdir()
    (machine / "active_coils.pickle").write_bytes(b"x")

    th = np.linspace(0, 2 * np.pi, 40)
    rr = 0.9 + 0.3 * np.cos(th)
    zz = 0.35 * np.sin(th)

    def fake_gs(**kwargs):
        class _Eq:
            plasma_psi = np.ones((8, 8))
            R = np.linspace(0.2, 1.5, 8)
            Z = np.linspace(-1, 1, 8)
            nx = ny = 8
            rboundary = rr
            zboundary = zz
            Raxis = 0.95
            Zaxis = 0.0

            def psi(self):
                return self.plasma_psi * 2.0

        return {"ok": True, "converged": True, "eq": _Eq()}

    fwd = run_efit_forward_replay(
        run_dir=run,
        t_s=0.3,
        machine_dir=machine,
        solve_gs_fn=fake_gs,
    )
    assert fwd["ok"] is True
    assert fwd["profile_source"] == "profile_trajectory"
    assert fwd["current_source"] == "measured_pf_at_compare_time"
    assert (run / "04_efit_compare" / "forward_replay" / "FORWARD_REPLAY.json").is_file()
    assert fwd["lcfs"] is not None

    cache = tmp_path / "cache"
    _write_mini_equilibrium_zarr(cache / "equilibrium.zarr")
    (run / "inputs" / "window.json").write_text(
        json.dumps({"t_start": 0.2, "t_end": 0.4}), encoding="utf-8"
    )
    (run / "presentation").mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {"R": 0.5 + 0.1 * np.cos(th), "Z": 0.1 * np.sin(th), "time": np.full(40, 0.3)}
    ).to_csv(run / "presentation" / "freegsnke_lcfs.csv", index=False)
    auth = load_efit_compare_authority(
        Path(__file__).resolve().parents[1] / "configs" / "efit_compare_authority.json"
    )
    import mast_freegsnke.efit_forward_replay as efr

    orig = efr.run_efit_forward_replay
    efr.run_efit_forward_replay = lambda **kwargs: fwd  # type: ignore
    try:
        rep = run_efit_compare(run, shot=30201, cache_dir=cache, auth=auth, machine_dir=machine)
    finally:
        efr.run_efit_forward_replay = orig  # type: ignore
    assert rep.ok is True
    assert rep.scorecard_source == "forward_replay"
    assert (rep.shape_scorecard or {}).get("compare_mode") == "forward_replay"
    rin = next(r for r in (rep.shape_scorecard or {})["rows"] if r["quantity"] == "R_in_midplane")
    assert rin["freegsnke"] is not None
    assert abs(float(rin["freegsnke"]) - float(np.min(rr[np.abs(zz) <= 0.05]))) < 0.05


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
