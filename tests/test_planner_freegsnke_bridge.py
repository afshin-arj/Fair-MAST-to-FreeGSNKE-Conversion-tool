"""Planner FreeGSNKE bridge (isoflux/Picard under freegsnke_python)."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mast_freegsnke.coil_limits import (
    load_coil_limits,
    resolve_measured_peak_limits,
    write_coil_limits,
)
from mast_freegsnke.planner import CircuitDynamics, load_planner_authority, write_circuit_dynamics
from mast_freegsnke.planner_freegsnke_bridge import (
    _RESULT_PREFIX,
    _parse_result_line,
    build_planner_job,
    freegsnke_importable,
    run_planner_stage_prefer_freegsnke,
)

REPO = Path(__file__).resolve().parents[1]
FREEG_PY = REPO / ".venv-freegsnke" / "Scripts" / "python.exe"
SHOT = REPO / "SHOT" / "30201"
ORDER = ["Solenoid", "P2_inner", "P2_outer", "P3", "P4", "P5", "P6"]


def test_parse_result_line() -> None:
    stdout = "noise\n" + _RESULT_PREFIX + json.dumps({"ok": True, "status": "ok"}) + "\n"
    parsed = _parse_result_line(stdout)
    assert parsed is not None
    assert parsed["ok"] is True


def test_build_planner_job_paths(tmp_path: Path) -> None:
    run = tmp_path / "SHOT" / "1"
    inputs = run / "inputs"
    inputs.mkdir(parents=True)
    job = build_planner_job(
        run_dir=run,
        inputs_dir=inputs,
        machine_dir=tmp_path / "machine",
        circuit_order=["Solenoid", "P4"],
        t_start=0.1,
        t_end=0.3,
        shot=1,
        cache_dir=tmp_path / "cache",
    )
    assert job["circuit_order"] == ["Solenoid", "P4"]
    assert "planner_authority_path" in job
    assert Path(job["inputs_dir"]) == inputs.resolve()


def test_prefer_in_process_when_no_freegsnke_python(tmp_path: Path) -> None:
    """Without freegsnke_python, run in-process (isoflux off for unit speed)."""
    run = tmp_path / "SHOT" / "9"
    inputs = run / "inputs"
    inputs.mkdir(parents=True)
    (inputs / "planner_authority").mkdir()
    t = np.linspace(0.1, 0.5, 21)
    cols = {c: np.full_like(t, 100.0 * (i + 1)) for i, c in enumerate(ORDER)}
    pd.DataFrame({"time": t, **cols}).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame({"time": t, **{c: np.full_like(t, 10.0) for c in ORDER}}).to_csv(
        inputs / "pf_voltages.csv", index=False
    )
    pl = load_planner_authority(REPO / "configs" / "planner_authority.json")
    pl = replace(
        pl,
        enable_isoflux=False,
        enable_picard=False,
        enable_psi_bry=False,
        n_knots=5,
    )
    (inputs / "planner_authority" / "planner_authority.json").write_text(
        json.dumps(pl.to_json_dict(), indent=2), encoding="utf-8"
    )
    cl = load_coil_limits(REPO / "configs" / "coil_limits_authority.json")
    cl = resolve_measured_peak_limits(
        cl,
        inputs_dir=inputs,
        circuit_order=ORDER,
        t_start=0.1,
        t_end=0.5,
        n_knots=5,
    )
    write_coil_limits(inputs, cl)
    n = len(ORDER)
    dyn = CircuitDynamics(
        circuit_order=ORDER,
        R_ohm=np.full(n, 0.01),
        L_henry=np.eye(n) * 1e-4,
        source="test",
        notes="unit",
    )
    write_circuit_dynamics(inputs / "circuit_dynamics_snapshot.json", dyn)
    ma = tmp_path / "machine"
    ma.mkdir()
    out = run_planner_stage_prefer_freegsnke(
        run_dir=run,
        inputs_dir=inputs,
        machine_dir=ma,
        planner_auth=pl,
        coil_limits=cl,
        circuit_order=ORDER,
        t_start=0.1,
        t_end=0.5,
        freegsnke_python=None,
        repo_root=REPO,
        shot=9,
        circuit_dynamics=dyn,
    )
    assert out["ok"] is True
    assert (run / "07_planner" / "PLANNER.json").is_file()
    meta = json.loads((run / "07_planner" / "PLANNER.json").read_text(encoding="utf-8"))
    assert meta.get("isoflux_cost") is False


@pytest.mark.skipif(not FREEG_PY.is_file(), reason=".venv-freegsnke not present")
@pytest.mark.skipif(
    not (SHOT / "inputs" / "pf_currents.csv").is_file()
    or not (REPO / "machine_authority" / "active_coils.pickle").is_file(),
    reason="SHOT/30201 + machine_authority required for isoflux smoke",
)
def test_smoke_bridge_isoflux_with_freegsnke_venv() -> None:
    """With FreeGSNKE venv, bridge should engage isoflux when shape targets exist."""
    import sys

    if freegsnke_importable() and Path(sys.executable).resolve() == FREEG_PY.resolve():
        pytest.skip("already running inside FreeGSNKE python — bridge short-circuits")

    from mast_freegsnke.coil_limits import load_coil_limits
    from mast_freegsnke.planner import load_circuit_dynamics, load_planner_authority
    from mast_freegsnke.voltage_map import load_voltage_map

    inputs = SHOT / "inputs"
    pl = load_planner_authority(inputs / "planner_authority" / "planner_authority.json")
    cl = load_coil_limits(inputs / "coil_limits_authority" / "coil_limits_authority.json")
    dyn = load_circuit_dynamics(inputs / "circuit_dynamics_snapshot.json")
    window = json.loads((inputs / "window.json").read_text(encoding="utf-8"))
    st = None
    st_path = inputs / "shape_targets_authority" / "shape_targets.json"
    if st_path.is_file():
        st = json.loads(st_path.read_text(encoding="utf-8"))

    vm = load_voltage_map(REPO / "configs" / "voltage_map.json")
    order = list(vm.machine_active_circuit_order)

    out = run_planner_stage_prefer_freegsnke(
        run_dir=SHOT,
        inputs_dir=inputs,
        machine_dir=REPO / "machine_authority",
        planner_auth=pl,
        coil_limits=cl,
        circuit_order=order,
        t_start=float(window["t_start"]),
        t_end=float(window["t_end"]),
        freegsnke_python=str(FREEG_PY),
        repo_root=REPO,
        shot=30201,
        circuit_dynamics=dyn,
        shape_targets=st,
        cache_dir=REPO / "data_cache" / "shot_30201",
        timeout_s=600.0,
    )
    assert out["ok"] is True
    meta = json.loads((SHOT / "07_planner" / "PLANNER.json").read_text(encoding="utf-8"))
    assert meta.get("isoflux_cost") is True, (
        meta.get("isoflux_status"),
        meta.get("isoflux_residuals", {}).get("note")
        if isinstance(meta.get("isoflux_residuals"), dict)
        else None,
    )
    assert meta.get("isoflux_status") == "ok"