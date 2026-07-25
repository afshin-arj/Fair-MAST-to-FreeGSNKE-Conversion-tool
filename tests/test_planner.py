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


def test_default_planner_off() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.execute_planner is False
    assert cfg.planner_authority_path
    assert cfg.coil_limits_authority_path


def test_coil_limits_awaiting_blocks_require_ready() -> None:
    auth = load_coil_limits(REPO / "configs" / "coil_limits_authority.json")
    assert auth.awaiting is True
    with pytest.raises(CoilLimitsError, match="awaiting"):
        auth.require_ready(ORDER)


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
    pl = load_planner_authority(REPO / "configs" / "planner_authority.json")

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
    meta = json.loads((out / "PLANNER.json").read_text(encoding="utf-8"))
    assert meta["drive_labels"]["P3"] == "ohmic_synthetic_IxR"
    assert meta["drive_labels"]["Solenoid"] == "measured_fairmast_V"


def test_planner_authority_load() -> None:
    auth = load_planner_authority(REPO / "configs" / "planner_authority.json")
    assert auth.output_relpath == "07_planner"
    assert auth.enabled is True
