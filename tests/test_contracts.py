
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mast_freegsnke.diagnostic_contracts import (
    load_contracts,
    resolve_contracts_for_run,
    validate_contracts,
)
from mast_freegsnke.synthetic_extract import extract_synthetic_by_contracts
from mast_freegsnke.metrics import compare_from_contracts
from mast_freegsnke.coil_map import CoilMap, apply_coil_map, load_coil_map, validate_coil_map


def test_contracts_and_metrics_roundtrip(tmp_path: Path) -> None:
    # Create synthetic experimental and synthetic CSVs
    exp_csv = tmp_path / "exp.csv"
    syn_csv = tmp_path / "syn.csv"

    t = np.linspace(0.0, 1.0, 11)
    y = np.sin(2 * np.pi * t)
    pd.DataFrame({"time": t, "sig": y}).to_csv(exp_csv, index=False)
    # synthetic slightly off
    pd.DataFrame({"time": t, "sig": y + 0.1}).to_csv(syn_csv, index=False)

    contracts_json = tmp_path / "contracts.json"
    contracts_json.write_text(
        json.dumps(
            {
                "version": "1.0",
                "diagnostics": [
                    {
                        "name": "sig1",
                        "dtype": "flux_loop",
                        "units": "arb",
                        "exp": {"csv": str(exp_csv), "time_col": "time", "value_col": "sig"},
                        "syn": {"csv": str(syn_csv), "time_col": "time", "value_col": "sig"},
                    }
                ],
            }
        )
    )

    contracts = load_contracts(contracts_json)
    rep = validate_contracts(contracts, require_files=True)
    assert rep["ok"]

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    syn_res = extract_synthetic_by_contracts(run_dir, contracts)
    assert syn_res.ok
    assert (run_dir / "synthetic" / "synthetic_flux_loop.csv").exists()

    met = compare_from_contracts(run_dir, contracts)
    assert met["n_scored"] == 1
    assert (run_dir / "metrics" / "reconstruction_metrics.json").exists()


def test_coil_map_validate(tmp_path: Path) -> None:
    cm_path = tmp_path / "coil_map.json"
    cm_path.write_text(
        json.dumps({"version": "1.0", "mapping": {"A": {"coil": "P2_inner", "scale": 1.0, "sign": 1}}})
    )
    cm = load_coil_map(cm_path)
    rep = validate_coil_map(cm)
    assert rep["ok"]


def test_apply_coil_map_binding(tmp_path: Path) -> None:
    raw = tmp_path / "pf_active_raw.csv"
    pd.DataFrame({"time": [0.0, 1.0], "P2_INNER_A": [10.0, 20.0], "P2_OUTER_A": [1.0, 2.0]}).to_csv(
        raw, index=False
    )
    coil_map = CoilMap(
        mapping={
            "P2_INNER_A": {"coil": "P2_inner", "scale": 1.0, "sign": 1},
            "P2_OUTER_A": {"coil": "P2_outer", "scale": 2.0, "sign": -1},
        },
        circuits={},
    )
    out = tmp_path / "pf_currents.csv"
    rep = apply_coil_map(raw, out, coil_map)
    assert rep["ok"], rep
    df = pd.read_csv(out)
    assert list(df["P2_inner"]) == [10.0, 20.0]
    assert list(df["P2_outer"]) == [-2.0, -4.0]


def test_apply_coil_map_rejects_duplicate_coil(tmp_path: Path) -> None:
    raw = tmp_path / "pf_active_raw.csv"
    pd.DataFrame({"time": [0.0], "A": [1.0], "B": [2.0]}).to_csv(raw, index=False)
    coil_map = CoilMap(
        mapping={
            "A": {"coil": "P2_inner", "scale": 1.0, "sign": 1},
            "B": {"coil": "P2_inner", "scale": 1.0, "sign": 1},
        },
        circuits={},
    )
    rep = apply_coil_map(raw, tmp_path / "out.csv", coil_map)
    assert not rep["ok"]
    assert any("duplicate_coil_target" in e for e in rep["errors"])


def test_apply_coil_map_circuits_sum(tmp_path: Path) -> None:
    raw = tmp_path / "pf_active_raw.csv"
    pd.DataFrame(
        {"time": [0.0, 1.0], "P2IL FEED": [1.0, 2.0], "P2IU FEED": [3.0, 4.0], "SOL": [10.0, 20.0]}
    ).to_csv(raw, index=False)
    coil_map = CoilMap(
        mapping={},
        circuits={
            "P2_inner": {
                "exp_columns": ["P2IL FEED", "P2IU FEED"],
                "combine": "sum",
                "scale": 1.0,
                "sign": 1,
            },
            "Solenoid": {"exp_columns": ["SOL"], "combine": "identity", "scale": 1.0, "sign": 1},
        },
    )
    out = tmp_path / "pf_currents.csv"
    rep = apply_coil_map(raw, out, coil_map)
    assert rep["ok"], rep
    df = pd.read_csv(out)
    assert list(df["P2_inner"]) == [4.0, 6.0]
    assert list(df["Solenoid"]) == [10.0, 20.0]


def test_apply_coil_map_p6_antisym_mean(tmp_path: Path) -> None:
    raw = tmp_path / "pf_active_raw.csv"
    pd.DataFrame(
        {"time": [0.0, 1.0], "P6L": [100.0, 200.0], "P6U": [-80.0, -180.0]}
    ).to_csv(raw, index=False)
    coil_map = CoilMap(
        mapping={},
        circuits={
            "P6": {
                "exp_columns": ["P6L", "P6U"],
                "combine": "antisym_mean",
                "scale": 1.0,
                "sign": 1,
            }
        },
    )
    out = tmp_path / "pf_currents.csv"
    rep = apply_coil_map(raw, out, coil_map)
    assert rep["ok"], rep
    df = pd.read_csv(out)
    # 0.5*(100-(-80))=90; 0.5*(200-(-180))=190
    assert list(df["P6"]) == pytest.approx([90.0, 190.0])
    # Sum would wrongly cancel toward ~20 / ~20 — antisym must not do that.
    assert abs(df["P6"].iloc[0] - 20.0) > 50.0


def test_shipped_coil_map_p6_is_antisym() -> None:
    from pathlib import Path

    cm = load_coil_map(Path(__file__).resolve().parents[1] / "configs" / "coil_map.json")
    rep = validate_coil_map(cm)
    assert rep["ok"], rep["errors"]
    assert cm.circuits["P6"]["combine"] == "antisym_mean"
    assert cm.circuits["P6"]["exp_columns"] == ["P6L", "P6U"]
    for series in ("P2_inner", "P2_outer", "P3", "P4", "P5"):
        assert cm.circuits[series]["combine"] == "mean", series


def test_apply_coil_map_series_mean_not_sum(tmp_path: Path) -> None:
    raw = tmp_path / "pf_active_raw.csv"
    pd.DataFrame(
        {"time": [0.0, 1.0], "P4L FEED": [100.0, 200.0], "P4U FEED": [100.0, 200.0]}
    ).to_csv(raw, index=False)
    coil_map = CoilMap(
        mapping={},
        circuits={
            "P4": {
                "exp_columns": ["P4L FEED", "P4U FEED"],
                "combine": "mean",
                "scale": 1.0,
                "sign": 1,
            }
        },
    )
    out = tmp_path / "pf_currents.csv"
    rep = apply_coil_map(raw, out, coil_map)
    assert rep["ok"], rep
    df = pd.read_csv(out)
    assert list(df["P4"]) == pytest.approx([100.0, 200.0])


def test_resolve_contracts_for_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "shot_1"
    (run_dir / "inputs").mkdir(parents=True)
    exp = run_dir / "inputs" / "magnetics.csv"
    syn = run_dir / "synthetic" / "synthetic_flux_loop.csv"
    syn.parent.mkdir(parents=True)
    pd.DataFrame({"time": [0.0], "FL1": [1.0]}).to_csv(exp, index=False)
    pd.DataFrame({"time": [0.0], "FL1": [1.1]}).to_csv(syn, index=False)

    cpath = tmp_path / "contracts.json"
    cpath.write_text(
        json.dumps(
            {
                "version": "1.0",
                "diagnostics": [
                    {
                        "name": "fl1",
                        "dtype": "flux_loop",
                        "exp": {"csv": "inputs/magnetics.csv", "time_col": "time", "value_col": "FL1"},
                        "syn": {
                            "csv": "synthetic/synthetic_flux_loop.csv",
                            "time_col": "time",
                            "value_col": "FL1",
                        },
                    }
                ],
            }
        )
    )
    contracts = resolve_contracts_for_run(cpath, run_dir)
    rep = validate_contracts(contracts, require_files=True)
    assert rep["ok"]
