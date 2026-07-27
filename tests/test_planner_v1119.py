"""Planner v11.19: evolutive A/B, require flags, SLSQP, Plotly, ψ_bry inventory."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from mast_freegsnke.coil_limits import CircuitLimit, CoilLimitsAuthority
from mast_freegsnke.config import AppConfig
from mast_freegsnke.evolutive_from_plan import load_evolutive_ab_compare, score_evolutive_ip_at
from mast_freegsnke.planner import (
    PlannerAuthority,
    PlannerError,
    load_planner_authority,
    run_planner_stage,
    solve_trajectory,
)
from mast_freegsnke.planner_plots import write_planner_iv_plotly
from mast_freegsnke_ui import artifacts as art

REPO = Path(__file__).resolve().parents[1]


def _mini_qp_inputs() -> dict:
    n_t, n = 5, 2
    I_tgt = np.ones((n_t, n)) * 100.0
    R = np.array([0.01, 0.02])
    L = np.diag([1e-6, 2e-6])
    return dict(
        I_target=I_tgt,
        R=R,
        L=L,
        dt=0.01,
        I_lo=np.full(n, -5000.0),
        I_hi=np.full(n, 5000.0),
        V_lo=np.full(n, -200.0),
        V_hi=np.full(n, 200.0),
        weight_track_I=1.0,
        weight_V=1e-6,
        weight_dI=1e-2,
        weight_d2I=1e-3,
        max_iterations=20,
    )


def test_planner_authority_require_flags_default_on() -> None:
    auth = load_planner_authority(REPO / "configs" / "planner_authority.json")
    assert auth.require_isoflux is True
    assert auth.require_picard is True
    assert auth.qp_solver == "projected_iter"
    assert auth.authority_version == "1.4.0"


def test_execute_evolutive_from_plan_default_on() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.execute_evolutive_from_plan is True


def test_solve_trajectory_slsqp_smoke() -> None:
    sol = solve_trajectory(qp_solver="slsqp", qp_rel_tol=1e-8, **_mini_qp_inputs())
    assert sol["qp_solver"] == "slsqp"
    assert sol["I"].shape == (5, 2)
    assert np.all(np.isfinite(sol["V"]))


def test_write_planner_iv_plotly_html(tmp_path: Path) -> None:
    t = np.linspace(0.0, 0.2, 11)
    order = ["P1"]
    I = np.column_stack([1000.0 * np.ones_like(t)])
    V = np.column_stack([10.0 * np.ones_like(t)])
    limits = CoilLimitsAuthority(
        authority_name="coil_limits",
        authority_version="test",
        status="ok",
        citation="unit",
        circuits={"P1": CircuitLimit(Imax_A=5000.0, Vmax_V=200.0)},
    )
    name = write_planner_iv_plotly(
        tmp_path,
        times=t,
        circuit_order=order,
        I_plan=I,
        I_meas=I,
        V_plan=V,
        V_obs=V,
        coil_limits=limits,
    )
    assert name == "planning_iv_interactive.html"
    html = (tmp_path / name).read_text(encoding="utf-8")
    assert "plotly" in html.lower()


def test_score_evolutive_ip_at_and_ab(tmp_path: Path) -> None:
    run = tmp_path / "run"
    evo = run / "03_reconstruction" / "evolutive"
    plan = run / "03_reconstruction" / "evolutive_plan"
    inputs = run / "inputs"
    evo.mkdir(parents=True)
    plan.mkdir(parents=True)
    inputs.mkdir(parents=True)
    t = np.linspace(0.2, 0.4, 5)
    pd.DataFrame({"time": t, "ip": 900000.0 * np.ones_like(t)}).to_csv(
        inputs / "ip.csv", index=False
    )
    pd.DataFrame({"t_abs": t, "Ip": 880000.0 * np.ones_like(t), "step_ok": [True] * 5}).to_csv(
        evo / "history.csv", index=False
    )
    pd.DataFrame({"t_abs": t, "Ip": 850000.0 * np.ones_like(t), "step_ok": [True] * 5}).to_csv(
        plan / "history.csv", index=False
    )
    meas = score_evolutive_ip_at(run, evolutive_relpath="03_reconstruction/evolutive")
    assert meas["ok"] is True
    assert meas["rms_A"] == pytest.approx(20000.0)
    ab = load_evolutive_ab_compare(run)
    assert ab["measured_voltages"]["ok"] is True
    assert ab["planned_voltages"]["ok"] is True
    assert ab["delta_rms_A"] == pytest.approx(30000.0)


def test_load_evolutive_ab_compare_ui(tmp_path: Path) -> None:
    run = tmp_path
    (run / "03_reconstruction" / "evolutive").mkdir(parents=True)
    (run / "inputs").mkdir(parents=True)
    out = art.load_evolutive_ab_compare(run)
    assert "measured_voltages" in out
    assert "detail" in out


def test_require_isoflux_raises_when_build_fails(tmp_path: Path) -> None:
    from mast_freegsnke.planner import CircuitDynamics

    run_dir = tmp_path / "run"
    inputs = run_dir / "inputs"
    machine = REPO / "machine_authority"
    inputs.mkdir(parents=True)
    order = ["Solenoid", "P1", "P2", "P3", "P4", "P5", "P6"]
    t = np.linspace(0.1, 0.3, 11)
    pd.DataFrame({"time": t, **{c: np.zeros_like(t) for c in order}}).to_csv(
        inputs / "pf_currents.csv", index=False
    )
    pd.DataFrame({"time": t, **{c: np.zeros_like(t) for c in order}}).to_csv(
        inputs / "pf_voltages.csv", index=False
    )
    cl = CoilLimitsAuthority(
        authority_name="coil_limits",
        authority_version="test",
        status="ok",
        citation="test",
        circuits={c: CircuitLimit(Imax_A=5000.0, Vmax_V=200.0) for c in order},
    )
    dyn = CircuitDynamics(
        circuit_order=order,
        R_ohm=np.ones(len(order)) * 0.01,
        L_henry=np.diag(np.ones(len(order)) * 1e-6),
        source="test",
    )
    auth = PlannerAuthority(
        enabled=True,
        require_isoflux=True,
        require_picard=False,
        enable_picard=False,
        n_knots=11,
    )
    with patch(
        "mast_freegsnke.planner_isoflux.build_isoflux_sensors_for_knots",
        side_effect=RuntimeError("no greens"),
    ):
        with pytest.raises(PlannerError, match="require_isoflux"):
            run_planner_stage(
                run_dir=run_dir,
                inputs_dir=inputs,
                machine_dir=machine,
                planner_auth=auth,
                coil_limits=cl,
                circuit_order=order,
                circuit_dynamics=dyn,
                t_start=0.1,
                t_end=0.3,
                shot=1,
            )
