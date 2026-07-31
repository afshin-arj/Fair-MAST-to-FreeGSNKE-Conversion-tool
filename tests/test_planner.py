"""ADR-004 Phase 2: coil limits gate + GSPulse-style planner (numpy QP)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mast_freegsnke.coil_limits import CoilLimitsError, load_coil_limits
from mast_freegsnke.config import AppConfig
from mast_freegsnke.planner import (
    CircuitDynamics,
    load_planner_authority,
    run_planner_stage,
    solve_trajectory_qp,
    voltages_from_dynamics,
    write_circuit_dynamics,
)

REPO = Path(__file__).resolve().parents[1]
ORDER = ["Solenoid", "P2_inner", "P2_outer", "P3", "P4", "P5", "P6"]


def _planner_auth_relaxed():
    """Unit-test planner auth without require_isoflux/picard (no shape_targets fixture)."""
    from dataclasses import replace

    auth = load_planner_authority(REPO / "configs" / "planner_authority.json")
    return replace(
        auth,
        require_isoflux=False,
        require_picard=False,
        enable_picard=False,
    )


def test_default_planner_on() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.execute_planner is True
    assert cfg.planner_authority_path
    assert cfg.coil_limits_authority_path
    assert cfg.circuit_dynamics_authority_path


def test_coil_limits_awaiting_blocks_require_ready(tmp_path: Path) -> None:
    p = tmp_path / "awaiting.json"
    p.write_text(
        json.dumps(
            {
                "authority_name": "coil_limits",
                "authority_version": "0.1.0",
                "status": "awaiting_authority",
                "circuits": {},
                "citation": None,
            }
        ),
        encoding="utf-8",
    )
    auth = load_coil_limits(p)
    assert auth.awaiting is True
    with pytest.raises(CoilLimitsError, match="awaiting"):
        auth.require_ready(ORDER)


def test_coil_limits_measured_peak_margin_policy() -> None:
    auth = load_coil_limits(REPO / "configs" / "coil_limits_authority.json")
    assert auth.awaiting is False
    assert auth.limit_policy == "measured_peak_margin"
    assert auth.margin_factor == 1.2


def test_resolve_measured_peak_limits(tmp_path: Path) -> None:
    from mast_freegsnke.coil_limits import resolve_measured_peak_limits

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    t = np.linspace(0.1, 0.5, 21)
    I = {c: (100.0 * (i + 1)) for i, c in enumerate(ORDER)}
    V = {c: (10.0 * (i + 1)) for i, c in enumerate(ORDER)}
    pd.DataFrame({"time": t, **{c: np.full_like(t, I[c]) for c in ORDER}}).to_csv(
        inputs / "pf_currents.csv", index=False
    )
    pd.DataFrame({"time": t, **{c: np.full_like(t, V[c]) for c in ORDER}}).to_csv(
        inputs / "pf_voltages.csv", index=False
    )
    policy = load_coil_limits(REPO / "configs" / "coil_limits_authority.json")
    resolved = resolve_measured_peak_limits(
        policy,
        inputs_dir=inputs,
        circuit_order=ORDER,
        t_start=0.1,
        t_end=0.5,
    )
    assert resolved.circuits["Solenoid"].Imax_A == pytest.approx(120.0)
    assert resolved.circuits["Solenoid"].Vmax_V == pytest.approx(12.0)
    assert resolved.resolution["margin_factor"] == 1.2


def test_resolve_measured_peak_limits_idle_circuit_zero_peak(tmp_path: Path) -> None:
    """Shot 30203 P6: measured |I|=0 in window must resolve to Imax=Vmax=0 (not invent)."""
    from mast_freegsnke.coil_limits import resolve_measured_peak_limits

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    t = np.linspace(0.1, 0.5, 21)
    I = {c: np.full_like(t, 100.0 * (i + 1)) for i, c in enumerate(ORDER)}
    V = {c: np.full_like(t, 10.0 * (i + 1)) for i, c in enumerate(ORDER)}
    I["P6"] = np.zeros_like(t)
    V["P6"] = np.zeros_like(t)
    pd.DataFrame({"time": t, **I}).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame({"time": t, **V}).to_csv(inputs / "pf_voltages.csv", index=False)
    policy = load_coil_limits(REPO / "configs" / "coil_limits_authority.json")
    resolved = resolve_measured_peak_limits(
        policy,
        inputs_dir=inputs,
        circuit_order=ORDER,
        t_start=0.1,
        t_end=0.5,
        R_ohm_by_circuit={c: 0.01 for c in ORDER},
    )
    assert resolved.circuits["P6"].Imax_A == pytest.approx(0.0)
    assert resolved.circuits["P6"].Vmax_V == pytest.approx(0.0)
    assert resolved.circuits["P6"].Imin_A == pytest.approx(0.0)
    assert "idle" in (resolved.circuits["P6"].notes or "").lower()
    assert resolved.circuits["Solenoid"].Imax_A == pytest.approx(120.0)

def test_resolve_measured_peak_limits_ohmic_nan_fallback(tmp_path: Path) -> None:
    from mast_freegsnke.coil_limits import resolve_measured_peak_limits

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    t = np.linspace(0.1, 0.5, 21)
    I = {c: np.full_like(t, 100.0 * (i + 1)) for i, c in enumerate(ORDER)}
    V = {c: np.full_like(t, 10.0 * (i + 1)) for i, c in enumerate(ORDER)}
    V["P3"] = np.full_like(t, np.nan)
    V["P6"] = np.full_like(t, np.nan)
    pd.DataFrame({"time": t, **I}).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame({"time": t, **V}).to_csv(inputs / "pf_voltages.csv", index=False)
    policy = load_coil_limits(REPO / "configs" / "coil_limits_authority.json")
    R = {c: 0.01 for c in ORDER}
    R["P3"] = 0.000948
    L = {c: 1e-6 for c in ORDER}
    L["P3"] = 0.000356
    resolved = resolve_measured_peak_limits(
        policy,
        inputs_dir=inputs,
        circuit_order=ORDER,
        t_start=0.1,
        t_end=0.5,
        R_ohm_by_circuit=R,
        L_henry_by_circuit=L,
    )
    assert resolved.resolution["peaks"]["P3"]["V_peak_source"] in {
        "ohmic_synthetic_IxR",
        "dynamics_RIdt",
        "dynamics_planner_knots",
    }
    assert resolved.circuits["P3"].Vmax_V > 0

def test_circuit_dynamics_authority_user_table(tmp_path: Path) -> None:
    from mast_freegsnke.circuit_dynamics_authority import (
        build_circuit_dynamics_from_authority,
        load_circuit_dynamics_authority,
    )

    auth = load_circuit_dynamics_authority(REPO / "configs" / "circuit_dynamics_authority.json")
    assert auth.awaiting is False
    assert "P4" in auth.circuits
    assert "Solenoid" in auth.circuits
    assert auth.circuits["Solenoid"].R_ohm == pytest.approx(0.03404)
    assert auth.circuits["Solenoid"].L_henry == pytest.approx(0.00294)
    dyn, meta = build_circuit_dynamics_from_authority(auth, circuit_order=ORDER)
    assert meta["filled_from_freegsnke"] == []
    assert dyn.R_ohm[ORDER.index("P4")] == pytest.approx(0.003740)
    assert dyn.L_henry[ORDER.index("P4"), ORDER.index("P4")] == pytest.approx(0.004095)
    assert dyn.R_ohm[ORDER.index("Solenoid")] == pytest.approx(0.03404)
    assert dyn.L_henry[ORDER.index("Solenoid"), ORDER.index("Solenoid")] == pytest.approx(0.00294)


def test_execute_planner_requires_paths(tmp_path: Path) -> None:
    base = json.loads((REPO / "configs" / "default.json").read_text(encoding="utf-8"))
    base["execute_planner"] = True
    base["coil_limits_authority_path"] = None
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="coil_limits_authority_path"):
        AppConfig.load(p)


def test_voltages_from_dynamics_shapes() -> None:
    n_t, n = 5, 3
    I = np.linspace(0, 1, n_t * n).reshape(n_t, n)
    R = np.ones(n)
    L = np.eye(n) * 0.1
    V = voltages_from_dynamics(I, R=R, L=L, dt=0.01)
    assert V.shape == (n_t, n)
    assert np.all(np.isfinite(V))


def test_solve_trajectory_qp_respects_I_bounds() -> None:
    n_t, n = 8, 2
    I_tgt = np.ones((n_t, n)) * 50.0
    I_tgt[:, 1] = 80.0
    R = np.array([0.01, 0.02])
    L = np.eye(2) * 1e-3
    sol = solve_trajectory_qp(
        I_target=I_tgt,
        R=R,
        L=L,
        dt=0.05,
        I_lo=np.array([-100.0, -100.0]),
        I_hi=np.array([60.0, 60.0]),
        V_lo=np.array([-1e6, -1e6]),
        V_hi=np.array([1e6, 1e6]),
        weight_track_I=1.0,
        weight_V=0.0,
        weight_dI=0.1,
        weight_d2I=0.01,
        max_iterations=20,
    )
    assert np.all(sol["I"] <= 60.0 + 1e-9)
    assert np.all(sol["I"] >= -100.0 - 1e-9)


def test_run_planner_stage_with_synthetic_dynamics(tmp_path: Path) -> None:
    run_dir = tmp_path / "30201"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    machine = tmp_path / "machine"
    machine.mkdir()

    t = np.linspace(0.1, 0.5, 21)
    I = {c: 1000.0 + 10.0 * i + 5.0 * np.sin(t) for i, c in enumerate(ORDER)}
    V = {c: 10.0 + i + np.cos(t) for i, c in enumerate(ORDER)}
    pd.DataFrame({"time": t, **I}).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame({"time": t, **V}).to_csv(inputs / "pf_voltages.csv", index=False)

    n = len(ORDER)
    dyn = CircuitDynamics(
        circuit_order=list(ORDER),
        R_ohm=np.full(n, 0.02),
        L_henry=np.eye(n) * 1e-3,
        source="test_synthetic",
    )
    write_circuit_dynamics(inputs / "circuit_dynamics_snapshot.json", dyn)

    limits_path = tmp_path / "limits.json"
    limits_path.write_text(
        json.dumps(
            {
                "authority_name": "coil_limits",
                "authority_version": "0.1.0",
                "status": "cited",
                "citation": "https://example.test/mast-pf-limits (fixture)",
                "circuits": {
                    c: {"Imax_A": 5e4, "Vmax_V": 2e3, "notes": "test fixture"} for c in ORDER
                },
                "notes": "test only",
            }
        ),
        encoding="utf-8",
    )
    cl = load_coil_limits(limits_path)
    pl = _planner_auth_relaxed()
    (run_dir / "contracts").mkdir(parents=True)
    (run_dir / "contracts" / "voltage_map.resolved.json").write_text(
        json.dumps(
            {
                "circuits": {
                    "Solenoid": {"combine": "identity"},
                    "P2_inner": {"combine": "identity"},
                    "P2_outer": {"combine": "identity"},
                    "P3": {"combine": "from_current_ohmic"},
                    "P4": {"combine": "identity"},
                    "P5": {"combine": "identity"},
                    "P6": {"combine": "from_current_ohmic"},
                }
            }
        ),
        encoding="utf-8",
    )

    rep = run_planner_stage(
        run_dir=run_dir,
        inputs_dir=inputs,
        machine_dir=machine,
        planner_auth=pl,
        coil_limits=cl,
        circuit_order=ORDER,
        t_start=0.1,
        t_end=0.5,
        shot=30201,
        circuit_dynamics=dyn,
    )
    assert rep["ok"] is True
    out = run_dir / "07_planner"
    assert (out / "planned_currents.csv").exists()
    assert (out / "planned_voltages.csv").exists()
    assert (out / "planning_residual_vs_measured_V.csv").exists()
    assert (out / "PLANNER.json").exists()
    assert (out / "planning_residual_timeseries.csv").exists()
    assert (out / "planning_voltage_by_circuit.png").exists()
    assert (out / "planning_current_by_circuit.png").exists()
    assert (out / "planning_voltage_delta.png").exists()
    assert (out / "planning_current_delta.png").exists()
    meta = json.loads((out / "PLANNER.json").read_text(encoding="utf-8"))
    assert meta["drive_labels"]["P3"] == "ohmic_synthetic_IxR"
    assert meta["drive_labels"]["Solenoid"] == "measured_fairmast_V"
    assert meta.get("residual_rms_mean_V") is not None
    assert meta.get("residual_rms_mean_deferred_ohmic_V") is not None
    assert (out / "voltage_model_gap.json").exists()
    assert meta.get("voltage_model_gap_overall") is not None
    resid = pd.read_csv(out / "planning_residual_vs_measured_V.csv")
    assert "gap_status" in resid.columns
    ohmic = resid[resid["residual_compare_class"] == "deferred_ohmic_synthetic"]
    assert len(ohmic) >= 1
    assert ohmic["rms_V"].apply(lambda x: np.isfinite(float(x))).all()
    md = (out / "PLANNER.md").read_text(encoding="utf-8")
    assert "planning_residual_timeseries.csv" in md
    assert "voltage_model_gap" in md
    assert meta.get("shape_targets_available", {}).get("note")


def test_planner_authority_load() -> None:
    auth = load_planner_authority(REPO / "configs" / "planner_authority.json")
    assert auth.output_relpath == "07_planner"
    assert auth.enabled is True


def test_planner_authority_rejects_string_bool(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text(
        json.dumps({"authority_name": "planner", "enabled": "false", "require": False}),
        encoding="utf-8",
    )
    from mast_freegsnke.planner import PlannerError

    with pytest.raises(PlannerError, match="enabled must be a JSON boolean"):
        load_planner_authority(p)


def test_solve_trajectory_qp_reports_V_violations() -> None:
    n_t, n = 6, 1
    I_tgt = np.ones((n_t, n)) * 100.0
    R = np.array([1.0])
    L = np.eye(1) * 1e-6
    sol = solve_trajectory_qp(
        I_target=I_tgt,
        R=R,
        L=L,
        dt=0.1,
        I_lo=np.array([-200.0]),
        I_hi=np.array([200.0]),
        V_lo=np.array([-1.0]),
        V_hi=np.array([1.0]),
        weight_track_I=1.0,
        weight_V=0.0,
        weight_dI=0.0,
        weight_d2I=0.0,
        max_iterations=5,
    )
    # V ≈ R I = 100 V >> ±1 V box
    assert sol["n_voltage_violations_raw"] > 0


def test_run_planner_stage_fails_closed_on_V_limits(tmp_path: Path) -> None:
    from mast_freegsnke.planner import PlannerError

    run_dir = tmp_path / "30201"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    machine = tmp_path / "machine"
    machine.mkdir()

    t = np.linspace(0.1, 0.5, 21)
    I = {c: 1000.0 + 10.0 * i for i, c in enumerate(ORDER)}
    V = {c: 10.0 + i for i, c in enumerate(ORDER)}
    pd.DataFrame({"time": t, **I}).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame({"time": t, **V}).to_csv(inputs / "pf_voltages.csv", index=False)

    n = len(ORDER)
    dyn = CircuitDynamics(
        circuit_order=list(ORDER),
        R_ohm=np.full(n, 0.05),
        L_henry=np.eye(n) * 1e-3,
        source="test_synthetic",
    )
    write_circuit_dynamics(inputs / "circuit_dynamics_snapshot.json", dyn)

    limits_path = tmp_path / "limits.json"
    limits_path.write_text(
        json.dumps(
            {
                "authority_name": "coil_limits",
                "authority_version": "0.1.0",
                "status": "cited",
                "citation": "https://example.test/mast-pf-limits (fixture)",
                "circuits": {
                    c: {"Imax_A": 5e4, "Vmax_V": 1.0, "notes": "tight V for fail-closed"}
                    for c in ORDER
                },
                "notes": "test only",
            }
        ),
        encoding="utf-8",
    )
    cl = load_coil_limits(limits_path)
    pl = _planner_auth_relaxed()

    with pytest.raises(PlannerError, match="voltage box constraints"):
        run_planner_stage(
            run_dir=run_dir,
            inputs_dir=inputs,
            machine_dir=machine,
            planner_auth=pl,
            coil_limits=cl,
            circuit_order=ORDER,
            t_start=0.1,
            t_end=0.5,
            shot=30201,
            circuit_dynamics=dyn,
        )
    meta = json.loads((run_dir / "07_planner" / "PLANNER.json").read_text(encoding="utf-8"))
    assert meta["status"] == "voltage_limit_violations"
    assert meta["n_voltage_violations_raw"] > 0


def test_run_planner_rejects_window_outside_pf_coverage(tmp_path: Path) -> None:
    from mast_freegsnke.planner import PlannerError

    run_dir = tmp_path / "30201"
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    machine = tmp_path / "machine"
    machine.mkdir()

    t = np.linspace(0.2, 0.4, 11)
    I = {c: 100.0 for c in ORDER}
    V = {c: 1.0 for c in ORDER}
    pd.DataFrame({"time": t, **I}).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame({"time": t, **V}).to_csv(inputs / "pf_voltages.csv", index=False)

    n = len(ORDER)
    dyn = CircuitDynamics(
        circuit_order=list(ORDER),
        R_ohm=np.full(n, 0.02),
        L_henry=np.eye(n) * 1e-3,
        source="test_synthetic",
    )
    write_circuit_dynamics(inputs / "circuit_dynamics_snapshot.json", dyn)

    limits_path = tmp_path / "limits.json"
    limits_path.write_text(
        json.dumps(
            {
                "authority_name": "coil_limits",
                "authority_version": "0.1.0",
                "status": "cited",
                "citation": "https://example.test/mast-pf-limits (fixture)",
                "circuits": {
                    c: {"Imax_A": 5e4, "Vmax_V": 2e3, "notes": "test"} for c in ORDER
                },
            }
        ),
        encoding="utf-8",
    )
    cl = load_coil_limits(limits_path)
    pl = _planner_auth_relaxed()

    with pytest.raises(PlannerError, match="not covered"):
        run_planner_stage(
            run_dir=run_dir,
            inputs_dir=inputs,
            machine_dir=machine,
            planner_auth=pl,
            coil_limits=cl,
            circuit_order=ORDER,
            t_start=0.1,
            t_end=0.5,
            shot=30201,
            circuit_dynamics=dyn,
        )


def test_resolve_measured_peak_limits_mutuals_matrix(tmp_path: Path) -> None:
    from mast_freegsnke.coil_limits import resolve_measured_peak_limits

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    t = np.linspace(0.1, 0.5, 21)
    # Rising currents so L dI/dt is nonzero
    cols_I = {"time": t}
    cols_V = {"time": t}
    for i, c in enumerate(ORDER):
        cols_I[c] = 100.0 * (i + 1) * (1.0 + 0.5 * (t - t[0]) / (t[-1] - t[0]))
        cols_V[c] = np.full_like(t, 1.0)  # tiny measured V so dynamics can win
    pd.DataFrame(cols_I).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame(cols_V).to_csv(inputs / "pf_voltages.csv", index=False)
    policy = load_coil_limits(REPO / "configs" / "coil_limits_authority.json")
    R = {c: 0.01 for c in ORDER}
    Ldiag = {c: 1e-4 for c in ORDER}
    n = len(ORDER)
    Lmat = np.diag([Ldiag[c] for c in ORDER]).astype(float)
    Lmat[0, 1] = Lmat[1, 0] = 5e-5  # mutual
    resolved = resolve_measured_peak_limits(
        policy,
        inputs_dir=inputs,
        circuit_order=ORDER,
        t_start=0.1,
        t_end=0.5,
        R_ohm_by_circuit=R,
        L_henry_by_circuit=Ldiag,
        L_henry_matrix=Lmat,
        n_knots=21,
    )
    assert resolved.resolution["dynamics_L_model"] == "full_matrix"
    # At least one circuit should cite mutuals dynamics source
    sources = [resolved.resolution["peaks"][c]["V_peak_source"] for c in ORDER]
    assert any("mutuals" in s for s in sources)


def test_planner_authority_picard_rel_tol() -> None:
    auth = load_planner_authority(REPO / "configs" / "planner_authority.json")
    assert auth.picard_rel_tol == pytest.approx(1.0e-3)
    assert auth.authority_version == "1.4.0"

