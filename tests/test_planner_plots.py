"""Unit tests for planner small-multiple I/V plots."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from mast_freegsnke.coil_limits import CircuitLimit, CoilLimitsAuthority
from mast_freegsnke.planner_plots import write_planner_iv_plots


def test_write_planner_iv_plots_small_multiples(tmp_path: Path) -> None:
    t = np.linspace(0.0, 0.4, 21)
    order = ["P1", "P3", "Solenoid"]
    I_meas = np.column_stack([1000.0 * np.sin(2 * np.pi * t), 500.0 * t, -2000.0 * np.ones_like(t)])
    I_plan = I_meas + 10.0
    V_obs = np.column_stack([50.0 * np.ones_like(t), 20.0 * t, 100.0 * np.cos(2 * np.pi * t)])
    V_plan = V_obs + 2.0
    limits = CoilLimitsAuthority(
        authority_name="coil_limits",
        authority_version="test",
        status="ok",
        citation="unit test",
        circuits={
            name: CircuitLimit(Imax_A=5000.0, Vmax_V=200.0)
            for name in order
        },
        limit_policy="fixed",
    )
    written = write_planner_iv_plots(
        tmp_path,
        times=t,
        circuit_order=order,
        I_plan=I_plan,
        I_meas=I_meas,
        V_plan=V_plan,
        V_obs=V_obs,
        coil_limits=limits,
        drive_labels={"P3": "ohmic_synthetic_IxR", "Solenoid": "measured_fairmast_V"},
    )
    assert written == [
        "planning_current_by_circuit.png",
        "planning_current_delta.png",
        "planning_voltage_by_circuit.png",
        "planning_voltage_delta.png",
    ]
    for name in written:
        p = tmp_path / name
        assert p.is_file()
        assert p.stat().st_size > 100
