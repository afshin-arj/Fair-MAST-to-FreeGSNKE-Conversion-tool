"""Planner voltage model-gap honesty (v11.32.0)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mast_freegsnke.planner import (
    build_voltage_model_gap,
    voltages_from_dynamics,
    _classify_voltage_gap_status,
)
from mast_freegsnke.certify import certify_run_dir
from mast_freegsnke.science_audit import planner_voltage_gap_audit


def test_voltages_from_dynamics_gap_identity() -> None:
    """When V_plan comes from the same I as V_dyn, plan−dyn RMS is ~0."""
    n_t, n = 11, 3
    t = np.linspace(0.0, 0.1, n_t)
    dt = float(t[1] - t[0])
    I = np.column_stack(
        [
            1.0e5 + 2.0e4 * np.sin(20 * t),
            -5.0e4 + 1.0e4 * np.cos(15 * t),
            3.0e4 * np.ones(n_t),
        ]
    )
    R = np.array([0.04, 0.002, 0.008], dtype=float)
    L = np.diag([0.003, 0.001, 0.002]).astype(float)
    V = voltages_from_dynamics(I, R=R, L=L, dt=dt)
    drive = {f"C{i}": "measured_fairmast_V" for i in range(n)}
    gap = build_voltage_model_gap(
        circuit_order=[f"C{i}" for i in range(n)],
        drive_labels=drive,
        I_plan=I,
        I_meas=I,
        V_plan=V,
        V_obs=V - 50.0,  # plan ahead of terminal → +50 V mean bias; tiny plan−dyn
        V_dyn=V,
        V_IxR=R * I,
        R_ohm=R,
        L_henry=L,
        dt=dt,
    )
    assert gap["overall_status"] == "model_gap_expected"
    assert gap["version"] == "1.2"
    assert int(gap["n_same_sign_model_gap"]) >= 2  # constant channel has no corr
    assert gap["overall_status_label"]
    for row in gap["circuits"]:
        assert row["i_track_rms_A"] == pytest.approx(0.0, abs=1e-9)
        assert row["rms_plan_minus_dyn_V"] == pytest.approx(0.0, abs=1e-9)
        assert row["rms_plan_minus_meas_V"] == pytest.approx(50.0, rel=1e-6)
        assert row["mean_bias_plan_minus_meas_V"] == pytest.approx(50.0, rel=1e-6)
        assert row["mean_bias_early_plan_minus_meas_V"] is not None
        assert row["rms_RI_V"] is not None and row["rms_RI_V"] > 0.0
        assert row["rms_L_dI_V"] is not None
        assert row["gap_status"] == "model_gap_expected"
        assert "Active-only" in (row.get("gap_status_label") or "")
        if row.get("corr_dyn_meas") is not None and float(row["corr_dyn_meas"]) > 0.0:
            assert row["same_sign_model_gap"] is True
            assert "not a polarity" in (row.get("honesty") or "").lower()
    assert "auto_flip_solenoid_p1" in gap["do_not"]
    assert "fit_CS_R_to_measured_V" in gap["do_not"]


def test_solenoid_like_gap_annex_fields() -> None:
    """Solenoid-like channel: bias / RI / L dI annex present; same-sign honesty."""
    n_t = 21
    t = np.linspace(0.0, 0.2, n_t)
    dt = float(t[1] - t[0])
    I = (1.0e5 + 5.0e3 * np.sin(30 * t)).reshape(-1, 1)
    R = np.array([0.045])
    L = np.array([[0.003]])
    V_dyn = voltages_from_dynamics(I, R=R, L=L, dt=dt)
    V_obs = V_dyn - 70.0  # plan−meas ≈ +70 V same-sign bias when V_plan=V_dyn
    gap = build_voltage_model_gap(
        circuit_order=["Solenoid"],
        drive_labels={"Solenoid": "measured_fairmast_V"},
        I_plan=I,
        I_meas=I,
        V_plan=V_dyn,
        V_obs=V_obs,
        V_dyn=V_dyn,
        V_IxR=R * I,
        R_ohm=R,
        L_henry=L,
        dt=dt,
    )
    row = gap["circuits"][0]
    assert row["gap_status"] == "model_gap_expected"
    assert row["same_sign_model_gap"] is True
    assert row["mean_bias_plan_minus_meas_V"] == pytest.approx(70.0, rel=1e-5)
    assert row["mean_bias_early_plan_minus_meas_V"] is not None
    assert row["corr_V_dIdt"] is not None
    assert row["rms_RI_V"] == pytest.approx(float(np.sqrt(np.mean((R[0] * I[:, 0]) ** 2))), rel=1e-5)
    assert row["rms_L_dI_V"] is not None and np.isfinite(row["rms_L_dI_V"])
    assert gap["n_same_sign_model_gap"] == 1
    honesty = (row.get("honesty") or "").lower()
    assert "p1" in honesty or "polarity" in honesty or "active-only" in honesty


def test_shipped_voltage_map_p4_p5_sign_restores_dIdt() -> None:
    """v2.2: P4/P5 sign=-1; Solenoid/P2 stay +1 (same-sign model gap, not flip)."""
    from mast_freegsnke.voltage_map import load_voltage_map, validate_voltage_map

    root = Path(__file__).resolve().parents[1]
    vmap = load_voltage_map(root / "configs" / "voltage_map.json")
    rep = validate_voltage_map(vmap)
    assert not rep.get("errors"), rep.get("errors")
    assert vmap.version == "2.2"
    assert int(vmap.circuits["P4"]["sign"]) == -1
    assert int(vmap.circuits["P5"]["sign"]) == -1
    assert int(vmap.circuits["Solenoid"]["sign"]) == 1
    assert int(vmap.circuits["P2_inner"]["sign"]) == 1
    assert int(vmap.circuits["P2_outer"]["sign"]) == 1

    assert (
        _classify_voltage_gap_status(
            drive_label="measured_fairmast_V",
            i_track_rms_A=1.0,
            rms_plan_minus_meas_V=100.0,
            rms_plan_minus_dyn_V=2.0,
            corr_dyn_meas=-0.95,
            corr_dyn_neg_meas=0.95,
        )
        == "polarity_suspect"
    )
    assert (
        _classify_voltage_gap_status(
            drive_label="ohmic_synthetic_IxR",
            i_track_rms_A=1.0,
            rms_plan_minus_meas_V=None,
            rms_plan_minus_dyn_V=1.0,
            corr_dyn_meas=None,
            corr_dyn_neg_meas=None,
        )
        == "deferred_ohmic_ixr"
    )


def test_ohmic_ixr_residual_finite_in_gap() -> None:
    n_t = 8
    I = np.linspace(1.0e4, 2.0e4, n_t).reshape(-1, 1)
    R = np.array([0.002])
    L = np.array([[0.001]])
    dt = 0.01
    V_dyn = voltages_from_dynamics(I, R=R, L=L, dt=dt)
    V_ixr = R * I
    # Planned inductive V differs from pure IxR — residual must be finite, not NaN.
    gap = build_voltage_model_gap(
        circuit_order=["P3"],
        drive_labels={"P3": "ohmic_synthetic_IxR"},
        I_plan=I,
        I_meas=I,
        V_plan=V_dyn,
        V_obs=np.full_like(I, np.nan),
        V_dyn=V_dyn,
        V_IxR=V_ixr,
        R_ohm=R,
    )
    row = gap["circuits"][0]
    assert row["gap_status"] == "deferred_ohmic_ixr"
    assert row["rms_plan_minus_meas_V"] is None
    assert row["rms_plan_minus_IxR_V"] is not None
    assert np.isfinite(row["rms_plan_minus_IxR_V"])
    assert row["rms_plan_minus_IxR_V"] > 0.0


def test_certify_warns_polarity_suspect(tmp_path: Path) -> None:
    evo = tmp_path / "07_planner"
    evo.mkdir()
    (tmp_path / "manifest.json").write_text(
        json.dumps({"status": "success", "blocking_errors": []}),
        encoding="utf-8",
    )
    (tmp_path / "provenance").mkdir()
    (evo / "voltage_model_gap.json").write_text(
        json.dumps(
            {
                "overall_status": "polarity_suspect",
                "n_polarity_suspect": 2,
                "n_model_gap_expected": 0,
                "mean_i_track_rms_A": 3.0,
            }
        ),
        encoding="utf-8",
    )
    (evo / "PLANNER.json").write_text(
        json.dumps(
            {
                "method": "gspulse_python",
                "method_version": "v1.5",
                "status": "ok",
                "picard": True,
                "isoflux_cost": True,
                "voltage_model_gap_overall": "polarity_suspect",
                "mean_i_track_rms_A": 3.0,
                "require_isoflux": True,
                "require_picard": True,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "inputs" / "planner_authority").mkdir(parents=True)
    (tmp_path / "inputs" / "planner_authority" / "planner_authority.json").write_text(
        json.dumps({"require_isoflux": True, "require_picard": True}),
        encoding="utf-8",
    )
    rep = certify_run_dir(tmp_path, skip_reviewer_pack=True, skip_replay=True)
    assert "planner_voltage_polarity_suspect" in rep["warnings"]
    assert rep["tier"] == "YELLOW"

    audit = planner_voltage_gap_audit(tmp_path)
    assert audit["available"] is True
    assert audit["overall_status"] == "polarity_suspect"


def test_run_planner_stage_writes_gap_and_finite_ohmic(tmp_path: Path) -> None:
    """Integration: residual CSV has gap fields; ohmic rms finite."""
    from mast_freegsnke.planner import (
        CircuitDynamics,
        PlannerAuthority,
        run_planner_stage,
        write_circuit_dynamics,
    )
    from mast_freegsnke.coil_limits import load_coil_limits

    order = ["Solenoid", "P3"]
    run_dir = tmp_path / "shot"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    machine = tmp_path / "machine"
    machine.mkdir()
    t = np.linspace(0.2, 0.3, 21)
    I = np.column_stack([1.0e4 * np.ones_like(t), 2.0e3 * np.ones_like(t)])
    V = np.column_stack([-50.0 * np.ones_like(t), np.full_like(t, np.nan)])
    pd.DataFrame({"time": t, "Solenoid": I[:, 0], "P3": I[:, 1]}).to_csv(
        inputs / "pf_currents.csv", index=False
    )
    pd.DataFrame({"time": t, "Solenoid": V[:, 0], "P3": V[:, 1]}).to_csv(
        inputs / "pf_voltages.csv", index=False
    )
    R = np.array([0.045, 0.002])
    L = np.diag([0.003, 0.001])
    dyn = CircuitDynamics(
        circuit_order=order,
        R_ohm=R,
        L_henry=L,
        source="test",
        notes="test",
    )
    write_circuit_dynamics(inputs / "circuit_dynamics_snapshot.json", dyn)
    (run_dir / "contracts").mkdir(parents=True)
    (run_dir / "contracts" / "voltage_map.resolved.json").write_text(
        json.dumps(
            {
                "circuits": {
                    "Solenoid": {"combine": "identity", "sign": 1, "scale": 1},
                    "P3": {
                        "combine": "from_current_ohmic",
                        "sign": 1,
                        "scale": 1,
                        "current_circuit": "P3",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    limits_path = tmp_path / "limits.json"
    limits_path.write_text(
        json.dumps(
            {
                "authority_name": "coil_limits",
                "authority_version": "0.1.0",
                "status": "cited",
                "citation": "test fixture",
                "circuits": {
                    "Solenoid": {"Imax_A": 2e5, "Vmax_V": 2e3, "notes": "t"},
                    "P3": {"Imax_A": 5e4, "Vmax_V": 5e2, "notes": "t"},
                },
                "notes": "test",
            }
        ),
        encoding="utf-8",
    )
    limits = load_coil_limits(limits_path)
    auth = PlannerAuthority(
        enabled=True,
        n_knots=11,
        enable_isoflux=False,
        require_isoflux=False,
        enable_picard=False,
        require_picard=False,
        enable_psi_bry=False,
        require_psi_bry=False,
        weight_track_I=1.0,
        weight_V=1e-6,
    )
    out = run_planner_stage(
        run_dir=run_dir,
        inputs_dir=inputs,
        machine_dir=machine,
        planner_auth=auth,
        coil_limits=limits,
        circuit_order=order,
        t_start=0.2,
        t_end=0.3,
        shot=1,
        circuit_dynamics=dyn,
    )
    assert out["ok"] is True
    gap_path = run_dir / "07_planner" / "voltage_model_gap.json"
    assert gap_path.is_file()
    resid = pd.read_csv(run_dir / "07_planner" / "planning_residual_vs_measured_V.csv")
    assert "gap_status" in resid.columns
    assert "mean_bias_plan_minus_meas_V" in resid.columns
    assert "rms_RI_V" in resid.columns
    assert "rms_L_dI_V" in resid.columns
    sol = resid[resid["circuit"] == "Solenoid"].iloc[0]
    assert sol["gap_status"] in ("model_gap_expected", "i_track_ok", "unknown")
    p3 = resid[resid["circuit"] == "P3"].iloc[0]
    assert p3["residual_compare_class"] == "deferred_ohmic_synthetic"
    assert np.isfinite(float(p3["rms_V"]))
    meta = json.loads((run_dir / "07_planner" / "PLANNER.json").read_text(encoding="utf-8"))
    assert meta["method_version"] == "v1.5"
    assert "voltage_model_gap" in meta
    md = (run_dir / "07_planner" / "PLANNER.md").read_text(encoding="utf-8")
    assert "voltage_model_gap" in md
    assert "I-track" in md or "I-track RMS" in md
