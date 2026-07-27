"""Path B0/B1: shape_targets authority + planner honesty labels."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mast_freegsnke.circuit_dynamics_authority import (
    CircuitDynamicsAuthority,
    CircuitRL,
    build_circuit_dynamics_from_authority,
)
from mast_freegsnke.config import AppConfig
from mast_freegsnke.planner import CircuitDynamics, load_planner_authority
from mast_freegsnke.shape_targets import (
    ShapeTargetsError,
    load_shape_targets_authority,
    run_shape_targets_stage,
)

REPO = Path(__file__).resolve().parents[1]
ORDER = ["Solenoid", "P2_inner", "P2_outer", "P3", "P4", "P5", "P6"]


def test_default_shape_targets_on() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.build_shape_targets is True
    assert cfg.shape_targets_authority_path


def test_load_shipped_shape_targets_authority() -> None:
    auth = load_shape_targets_authority(REPO / "configs" / "shape_targets_authority.json")
    assert auth.enabled is True
    assert auth.require is False
    assert auth.source == "fairmast_level2_equilibrium"
    assert auth.tokamark_aligned is True


def test_shape_targets_soft_skip_missing_cache(tmp_path: Path) -> None:
    auth = load_shape_targets_authority(REPO / "configs" / "shape_targets_authority.json")
    run_dir = tmp_path / "SHOT" / "1"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    cache = tmp_path / "cache_empty"
    cache.mkdir()
    rep = run_shape_targets_stage(
        run_dir=run_dir,
        inputs_dir=inputs,
        cache_dir=cache,
        auth=auth,
        t_start=0.1,
        t_end=0.4,
        n_knots_override=5,
    )
    assert rep["status"] == "skipped_insufficient_archive"
    assert rep["ok"] is True  # require=false
    assert (inputs / "shape_targets_authority" / "shape_targets.json").is_file()
    assert (run_dir / "07_planner" / "shape_targets.json").is_file()


def test_shape_targets_require_blocks(tmp_path: Path) -> None:
    auth = load_shape_targets_authority(REPO / "configs" / "shape_targets_authority.json")
    # force require
    from mast_freegsnke.shape_targets import ShapeTargetsAuthority

    auth = ShapeTargetsAuthority(
        **{**auth.to_json_dict(), "require": True, "shape_scalars": list(auth.shape_scalars),
           "lcfs_vars": list(auth.lcfs_vars)}
    )
    run_dir = tmp_path / "SHOT" / "2"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    with pytest.raises(ShapeTargetsError, match="require=true"):
        run_shape_targets_stage(
            run_dir=run_dir,
            inputs_dir=inputs,
            cache_dir=tmp_path / "nope",
            auth=auth,
            t_start=0.1,
            t_end=0.4,
        )


def test_circuit_dynamics_prefer_mutuals_from_fill() -> None:
    auth = CircuitDynamicsAuthority(
        authority_name="circuit_dynamics",
        authority_version="1.0.0",
        status="cited",
        citation="unit-test",
        L_model="diagonal_self_only",
        prefer_freegsnke_mutuals=True,
        missing_circuits_policy="fail",
        circuits={
            c: CircuitRL(R_ohm=0.01 * (i + 1), L_henry=1e-4 * (i + 1))
            for i, c in enumerate(ORDER)
        },
    )
    n = len(ORDER)
    L = np.eye(n) * 1e-3
    L[0, 1] = L[1, 0] = 2e-4  # mutual
    fill = CircuitDynamics(
        circuit_order=ORDER,
        R_ohm=np.full(n, 0.05),
        L_henry=L,
        source="freegsnke_test",
    )
    dyn, notes = build_circuit_dynamics_from_authority(
        auth, circuit_order=ORDER, freegsnke_fill=fill
    )
    assert notes["mutuals"] == "freegsnke_offdiag_retained_cited_Lii_overlay"
    assert dyn.L_henry[0, 1] == pytest.approx(2e-4)
    assert dyn.L_henry[0, 0] == pytest.approx(1e-4)  # cited L_ii overlay
    assert dyn.R_ohm[0] == pytest.approx(0.01)


def test_circuit_dynamics_diagonal_fallback_loud() -> None:
    auth = CircuitDynamicsAuthority(
        authority_name="circuit_dynamics",
        authority_version="1.0.0",
        status="cited",
        citation="unit-test",
        L_model="diagonal_self_only",
        prefer_freegsnke_mutuals=False,
        missing_circuits_policy="fail",
        circuits={
            c: CircuitRL(R_ohm=0.01, L_henry=1e-3) for c in ORDER
        },
    )
    dyn, notes = build_circuit_dynamics_from_authority(auth, circuit_order=ORDER)
    assert notes["mutuals"] == "neglected_diagonal_self_only_declared"
    assert float(np.max(np.abs(dyn.L_henry - np.diag(np.diag(dyn.L_henry))))) == 0.0
    assert "mutuals_neglected" in dyn.source


def test_planner_honesty_labels_in_meta(tmp_path: Path) -> None:
    from mast_freegsnke.coil_limits import load_coil_limits, resolve_measured_peak_limits
    from mast_freegsnke.planner import run_planner_stage

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    run_dir = tmp_path
    t = np.linspace(0.1, 0.5, 21)
    I = {c: np.full_like(t, 100.0 * (i + 1)) for i, c in enumerate(ORDER)}
    V = {c: np.full_like(t, 10.0 * (i + 1)) for i, c in enumerate(ORDER)}
    pd.DataFrame({"time": t, **I}).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame({"time": t, **V}).to_csv(inputs / "pf_voltages.csv", index=False)

    pl_auth = load_planner_authority(REPO / "configs" / "planner_authority.json")
    from dataclasses import replace

    pl_auth = replace(pl_auth, require_isoflux=False, require_picard=False, enable_picard=False)
    cl = resolve_measured_peak_limits(
        load_coil_limits(REPO / "configs" / "coil_limits_authority.json"),
        inputs_dir=inputs,
        circuit_order=ORDER,
        t_start=0.1,
        t_end=0.5,
        R_ohm_by_circuit={c: 0.01 for c in ORDER},
        L_henry_by_circuit={c: 1e-4 for c in ORDER},
        n_knots=int(pl_auth.n_knots),
    )
    n = len(ORDER)
    dyn = CircuitDynamics(
        circuit_order=ORDER,
        R_ohm=np.full(n, 0.01),
        L_henry=np.eye(n) * 1e-4,
        source="unit_test_diagonal",
        notes="mutuals=neglected_diagonal_self_only_declared",
    )
    # Seed empty shape targets payload
    st_root = inputs / "shape_targets_authority"
    st_root.mkdir(parents=True)
    (st_root / "shape_targets.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "present": True,
                "n_knots": 5,
                "found_scalars": ["wmhd"],
                "n_knots_with_lcfs_control_points": 0,
            }
        ),
        encoding="utf-8",
    )
    out = run_planner_stage(
        run_dir=run_dir,
        inputs_dir=inputs,
        machine_dir=tmp_path,  # unused when dynamics provided
        planner_auth=pl_auth,
        coil_limits=cl,
        circuit_order=ORDER,
        t_start=0.1,
        t_end=0.5,
        shot=1,
        circuit_dynamics=dyn,
    )
    meta = json.loads((run_dir / "07_planner" / "PLANNER.json").read_text(encoding="utf-8"))
    assert meta["method"] == "gspulse_python"
    assert meta["picard"] is False
    assert meta["isoflux_cost"] is False
    assert meta["shape_targets_available"]["present"] is True
    assert out["ok"] is True


def test_certify_yellow_for_incomplete_gspulse_python(tmp_path: Path) -> None:
    from mast_freegsnke.certify import certify_run_dir

    run_dir = tmp_path / "SHOT" / "9"
    (run_dir / "07_planner").mkdir(parents=True)
    (run_dir / "provenance").mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"status": "success", "blocking_errors": []}),
        encoding="utf-8",
    )
    (run_dir / "07_planner" / "PLANNER.json").write_text(
        json.dumps(
            {
                "method": "gspulse_python",
                "method_version": "v1",
                "picard": False,
                "isoflux_cost": False,
                "status": "ok",
                "shape_targets_available": {"present": True},
            }
        ),
        encoding="utf-8",
    )
    report = certify_run_dir(run_dir, skip_replay=True, skip_reviewer_pack=True)
    assert report["tier"] == "YELLOW"
    assert any("picard_not_wired" in w for w in report["warnings"])
    assert any("isoflux_not_wired" in w for w in report["warnings"])


def test_certify_warns_voltage_exceeds_measured_peak_margin(tmp_path: Path) -> None:
    from mast_freegsnke.certify import certify_run_dir

    run_dir = tmp_path / "SHOT" / "10"
    (run_dir / "07_planner").mkdir(parents=True)
    (run_dir / "provenance").mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"status": "success", "blocking_errors": []}),
        encoding="utf-8",
    )
    (run_dir / "07_planner" / "PLANNER.json").write_text(
        json.dumps(
            {
                "method": "gspulse_python",
                "method_version": "v1.3",
                "picard": True,
                "isoflux_cost": True,
                "status": "voltage_exceeds_measured_peak_margin",
                "shape_targets_available": {"present": True},
            }
        ),
        encoding="utf-8",
    )
    report = certify_run_dir(run_dir, skip_replay=True, skip_reviewer_pack=True)
    assert any(
        w == "planner_voltage_exceeds_measured_peak_margin" for w in report["warnings"]
    )

def test_relative_flux_and_qp_isoflux_pull() -> None:
    from mast_freegsnke.planner import solve_trajectory_qp
    from mast_freegsnke.planner_isoflux import IsofluxSensors, relative_flux_matrix

    G = np.array([[1.0, 0.0], [2.0, 1.0], [3.0, 2.0]], dtype=float)
    G_rel = relative_flux_matrix(G, ref_index=2)  # max_R-like last row
    assert G_rel.shape == (2, 2)
    assert np.allclose(G_rel[0], [1.0 - 3.0, 0.0 - 2.0])

    n_t, n = 5, 2
    I_tgt = np.ones((n_t, n)) * 10.0
    # Isoflux: want G @ I ≈ 0 with G = [[1, 0]] → pulls I0 toward 0 vs track
    sens = IsofluxSensors(
        G=np.array([[1.0, 0.0]]),
        target=np.zeros(1),
        labels=("iso0",),
        kind="isoflux_rel",
        r_m=np.array([1.0]),
        z_m=np.array([0.0]),
    )
    pack = {
        "ok": True,
        "knots": [{"isoflux": sens, "xpoint_B": None} for _ in range(n_t)],
    }
    sol0 = solve_trajectory_qp(
        I_target=I_tgt,
        R=np.array([0.01, 0.01]),
        L=np.eye(2) * 1e-4,
        dt=0.01,
        I_lo=np.full(2, -1e6),
        I_hi=np.full(2, 1e6),
        V_lo=np.full(2, -1e6),
        V_hi=np.full(2, 1e6),
        weight_track_I=1.0,
        weight_V=0.0,
        weight_dI=0.0,
        weight_d2I=0.0,
        max_iterations=20,
        isoflux_pack=None,
        weight_isoflux=0.0,
    )
    sol1 = solve_trajectory_qp(
        I_target=I_tgt,
        R=np.array([0.01, 0.01]),
        L=np.eye(2) * 1e-4,
        dt=0.01,
        I_lo=np.full(2, -1e6),
        I_hi=np.full(2, 1e6),
        V_lo=np.full(2, -1e6),
        V_hi=np.full(2, 1e6),
        weight_track_I=1.0,
        weight_V=0.0,
        weight_dI=0.0,
        weight_d2I=0.0,
        max_iterations=20,
        isoflux_pack=pack,
        weight_isoflux=100.0,
        weight_xpoint_B=0.0,
    )
    # Strong isoflux on circuit 0 should pull |I[:,0]| below pure tracking (~10)
    assert float(np.mean(np.abs(sol1["I"][:, 0]))) < float(np.mean(np.abs(sol0["I"][:, 0])))


def test_isoflux_soft_skip_no_shape() -> None:
    from mast_freegsnke.planner_isoflux import build_isoflux_sensors_for_knots

    pack = build_isoflux_sensors_for_knots(
        machine_dir=Path("."),
        circuit_order=ORDER,
        shape_targets={"present": False},
    )
    assert pack["ok"] is False
    assert pack["status"] == "skipped_no_shape_targets"


def test_planner_authority_isoflux_fields() -> None:
    auth = load_planner_authority(REPO / "configs" / "planner_authority.json")
    assert auth.authority_version == "1.4.0"
    assert auth.enable_isoflux is True
    assert auth.require_isoflux is True
    assert auth.weight_isoflux > 0
    assert auth.isoflux_ref_policy == "max_R"
    assert auth.enable_picard is True
    assert auth.require_picard is True
    assert auth.max_picard_iterations >= 1
    assert auth.enable_psi_bry is True
    assert auth.weight_psi_bry > 0


def test_vloop_and_ejima_integrate() -> None:
    from mast_freegsnke.planner_plasma_scalars import (
        integrate_ejima_to_psi,
        integrate_vloop_to_psi,
        load_plasma_scalars_authority,
    )

    t = np.linspace(0.0, 1.0, 5)
    v = np.ones_like(t) * 2.0  # 2 V
    psi = integrate_vloop_to_psi(times=t, vloop_V=v, psi0=10.0)
    assert psi[0] == pytest.approx(10.0)
    assert psi[-1] == pytest.approx(10.0 - 2.0 * 1.0)

    Ip = np.linspace(1e5, 2e5, 5)
    psi_e = integrate_ejima_to_psi(
        times=t, Ip_A=Ip, R_p_ohm=0.0, L_I_henry=1e-6, psi0=0.0
    )
    # with Rp=0: Vp = L_I dIp/dt ≈ const → ψ decreases linearly
    assert psi_e[0] == pytest.approx(0.0)
    assert psi_e[-1] < 0.0

    auth = load_plasma_scalars_authority(REPO / "configs" / "plasma_scalars_authority.json")
    assert auth.ejima.status == "awaiting_authority"
    assert auth.enabled is True


def test_build_psi_bry_archive_and_ejima_awaiting() -> None:
    from mast_freegsnke.planner_plasma_scalars import (
        build_psi_bry_targets,
        load_plasma_scalars_authority,
    )
    from dataclasses import replace
    from mast_freegsnke.planner_plasma_scalars import EjimaAuthority

    auth = load_plasma_scalars_authority(REPO / "configs" / "plasma_scalars_authority.json")
    t = np.linspace(0.1, 0.5, 5)
    st = {
        "present": True,
        "knots": [
            {
                "t_s": float(tt),
                "scalars": {"psi_boundary": 1.0 + 0.1 * i, "vloop_dynamic": 2.0},
            }
            for i, tt in enumerate(t)
        ],
    }
    out = build_psi_bry_targets(times=t, auth=auth, shape_targets=st)
    assert out["ok"] is True
    assert out["mode"] == "archive_psi_bry"
    assert len(out["psi_bry_Wb"]) == 5

    # Without psi_bry but with vloop+psi0
    st2 = {
        "present": True,
        "knots": [
            {
                "t_s": float(tt),
                "scalars": {
                    "psi_boundary": 5.0 if i == 0 else None,
                    "vloop_dynamic": 1.0,
                },
            }
            for i, tt in enumerate(t)
        ],
    }
    # Force skip archive_psi_bry by clearing psi on later knots — first mode still finds series
    # Prefer testing vloop by removing psi_bry vars from priority via custom auth
    auth_vl = replace(
        auth,
        mode_priority=("archive_vloop_integrate", "ejima_cited_Rp_LI"),
        psi_bry_vars=("psi_boundary",),
        vloop_vars=("vloop_dynamic",),
    )
    st_vl = {
        "present": True,
        "knots": [
            {"t_s": float(tt), "scalars": {"psi_boundary": 5.0, "vloop_dynamic": 1.0}}
            for tt in t
        ],
    }
    out_vl = build_psi_bry_targets(times=t, auth=auth_vl, shape_targets=st_vl)
    assert out_vl["ok"] is True
    assert out_vl["mode"] == "archive_vloop_integrate"

    auth_ej = replace(
        auth,
        mode_priority=("ejima_cited_Rp_LI",),
        ejima=EjimaAuthority(status="awaiting_authority", notes="unit"),
    )
    out_ej = build_psi_bry_targets(times=t, auth=auth_ej, shape_targets=st, Ip_A=np.ones(5) * 1e5)
    assert out_ej["ok"] is False
    assert any(a.get("status") == "ejima_awaiting_authority" for a in out_ej["attempts"])


def test_attach_psi_bry_sensors_and_qp_weight() -> None:
    from mast_freegsnke.planner_isoflux import IsofluxSensors
    from mast_freegsnke.planner_plasma_scalars import attach_psi_bry_sensors
    from mast_freegsnke.planner import solve_trajectory_qp

    n_t, n = 4, 2
    G_full = np.array([[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]], dtype=float)
    sens = IsofluxSensors(
        G=np.array([[0.0, 0.0]]),
        target=np.zeros(1),
        labels=("dummy",),
        kind="isoflux_rel",
        r_m=np.array([1.0]),
        z_m=np.array([0.0]),
        r_all_m=np.array([1.0, 1.1, 1.2]),
        z_all_m=np.zeros(3),
        ref_index=0,
        G_psi_full=G_full,
    )
    pack = {"ok": True, "knots": [{"isoflux": sens, "xpoint_B": None} for _ in range(n_t)]}
    pack = attach_psi_bry_sensors(pack, psi_bry_Wb=[10.0] * n_t)
    assert pack["psi_bry_sensors"] == n_t
    assert pack["knots"][0]["psi_bry"].target[0] == pytest.approx(10.0)

    I0 = np.ones((n_t, n)) * 5.0
    sol = solve_trajectory_qp(
        I_target=I0,
        R=np.array([0.01, 0.01]),
        L=np.eye(2) * 1e-4,
        dt=0.1,
        I_lo=np.full(2, -1e6),
        I_hi=np.full(2, 1e6),
        V_lo=np.full(2, -1e6),
        V_hi=np.full(2, 1e6),
        weight_track_I=0.1,
        weight_V=0.0,
        weight_dI=0.0,
        weight_d2I=0.0,
        max_iterations=30,
        isoflux_pack=pack,
        weight_isoflux=0.0,
        weight_xpoint_B=0.0,
        weight_psi_bry=50.0,
    )
    # mean(G)=[1,0] → pulls I0 toward 10
    assert float(np.mean(sol["I"][:, 0])) > float(np.mean(I0[:, 0]))


def test_plasma_picard_offset_math() -> None:
    from mast_freegsnke.planner_isoflux import IsofluxSensors
    from mast_freegsnke.planner_picard import apply_plasma_offsets_to_sensors

    G_full = np.array([[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]], dtype=float)
    G_rel = G_full[:2] - G_full[2:3]  # wrong — use relative_flux
    from mast_freegsnke.planner_isoflux import relative_flux_matrix

    G_rel = relative_flux_matrix(G_full, ref_index=2)
    sens = IsofluxSensors(
        G=G_rel,
        target=np.zeros(2),
        labels=("a", "b"),
        kind="isoflux_rel",
        r_m=np.array([1.0, 1.1]),
        z_m=np.array([0.0, 0.1]),
        r_all_m=np.array([1.0, 1.1, 1.2]),
        z_all_m=np.array([0.0, 0.1, 0.0]),
        ref_index=2,
        G_psi_full=G_full,
    )
    I = np.array([10.0, 0.0])
    # total psi = vac + plasma; invent plasma = [1, 2, 4]
    psi_vac = G_full @ I
    psi_plasma = np.array([1.0, 2.0, 4.0])
    psi_tot = psi_vac + psi_plasma
    iso2, _ = apply_plasma_offsets_to_sensors(
        isoflux=sens, xpoint_B=None, I_k=I, psi_total=psi_tot
    )
    assert iso2 is not None
    # target = -(plasma_i - plasma_ref)
    assert np.allclose(iso2.target, -np.array([1.0 - 4.0, 2.0 - 4.0]))


def test_picard_outer_with_mock_gs(tmp_path: Path) -> None:
    from mast_freegsnke.execution_authority import write_execution_authority
    from mast_freegsnke.planner_isoflux import IsofluxSensors
    from mast_freegsnke.planner_picard import run_picard_outer_loop
    from mast_freegsnke.planner import solve_trajectory_qp

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    write_execution_authority(inputs, metrics_n_times=5)
    t = np.linspace(0.1, 0.5, 5)
    pd.DataFrame({"time": t, "Ip": np.full_like(t, 5e5)}).to_csv(
        inputs / "ip.csv", index=False
    )

    n_t, n = 5, 2
    G = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=float)
    sens = IsofluxSensors(
        G=G,
        target=np.zeros(2),
        labels=("a", "b"),
        kind="isoflux_rel",
        r_m=np.array([1.0, 1.1]),
        z_m=np.array([0.0, 0.0]),
        r_all_m=np.array([1.0, 1.1, 1.2]),
        z_all_m=np.array([0.0, 0.0, 0.0]),
        ref_index=2,
        G_psi_full=np.vstack([G, [0.5, 0.5]]),
    )
    pack = {
        "ok": True,
        "knots": [{"isoflux": sens, "xpoint_B": None} for _ in range(n_t)],
    }
    I0 = np.ones((n_t, n)) * 10.0

    class _Eq:
        def psiRZ(self, r, z):
            r = np.asarray(r, dtype=float).ravel()
            # Spatially varying total ψ so relative plasma offset ≠ 0
            return 3.0 + 0.5 * r

    def fake_gs(**kwargs):
        return {"ok": True, "converged": True, "eq": _Eq(), "tokamak": object()}

    qp_kwargs = {
        "I_target": I0,
        "R": np.array([0.01, 0.01]),
        "L": np.eye(2) * 1e-4,
        "dt": 0.1,
        "I_lo": np.full(2, -1e6),
        "I_hi": np.full(2, 1e6),
        "V_lo": np.full(2, -1e6),
        "V_hi": np.full(2, 1e6),
        "weight_track_I": 1.0,
        "weight_V": 0.0,
        "weight_dI": 0.0,
        "weight_d2I": 0.0,
        "max_iterations": 10,
        "weight_isoflux": 5.0,
        "weight_xpoint_B": 0.0,
    }
    out = run_picard_outer_loop(
        machine_dir=tmp_path,
        inputs_dir=inputs,
        circuit_order=["A", "B"],
        times=t,
        I_plan=I0,
        isoflux_pack=pack,
        qp_kwargs=qp_kwargs,
        max_picard_iterations=1,
        solve_gs_fn=fake_gs,
        solve_qp_fn=solve_trajectory_qp,
    )
    assert out["picard"] is True
    assert out["ok"] is True
    assert out["picard_mode"] == "forward_gs_freeze_plasma_offsets"
    # targets should no longer be all zeros after Picard
    iso = out["isoflux_pack"]["knots"][0]["isoflux"]
    assert not np.allclose(iso.target, 0.0)


def test_certify_yellow_picard_only_when_isoflux_true(tmp_path: Path) -> None:
    from mast_freegsnke.certify import certify_run_dir

    run_dir = tmp_path / "SHOT" / "10"
    (run_dir / "07_planner").mkdir(parents=True)
    (run_dir / "provenance").mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"status": "success", "blocking_errors": []}),
        encoding="utf-8",
    )
    (run_dir / "07_planner" / "PLANNER.json").write_text(
        json.dumps(
            {
                "method": "gspulse_python",
                "method_version": "v1.1",
                "picard": False,
                "isoflux_cost": True,
                "isoflux_mode": "vacuum_coil_greens",
                "status": "ok",
                "shape_targets_available": {"present": True},
            }
        ),
        encoding="utf-8",
    )
    report = certify_run_dir(run_dir, skip_replay=True, skip_reviewer_pack=True)
    assert report["tier"] == "YELLOW"
    assert any("picard_not_wired" in w for w in report["warnings"])
    assert not any("isoflux_not_wired" in w for w in report["warnings"])


def test_certify_no_picard_warn_when_picard_true(tmp_path: Path) -> None:
    from mast_freegsnke.certify import certify_run_dir

    run_dir = tmp_path / "SHOT" / "11"
    (run_dir / "07_planner").mkdir(parents=True)
    (run_dir / "provenance").mkdir(parents=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"status": "success", "blocking_errors": []}),
        encoding="utf-8",
    )
    (run_dir / "07_planner" / "PLANNER.json").write_text(
        json.dumps(
            {
                "method": "gspulse_python",
                "method_version": "v1.2",
                "picard": True,
                "picard_mode": "forward_gs_freeze_plasma_offsets",
                "isoflux_cost": True,
                "isoflux_mode": "vacuum_coil_greens_plus_plasma_picard",
                "status": "ok",
                "shape_targets_available": {"present": True},
            }
        ),
        encoding="utf-8",
    )
    report = certify_run_dir(run_dir, skip_replay=True, skip_reviewer_pack=True)
    assert not any("picard_not_wired" in w for w in report["warnings"])
    assert not any("isoflux_not_wired" in w for w in report["warnings"])
