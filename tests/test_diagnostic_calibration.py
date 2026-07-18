"""Tests for optional diagnostic calibration authority (v10.6.0)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mast_freegsnke.contracts_status import diagnostic_calibration_status_line
from mast_freegsnke.config import AppConfig
from mast_freegsnke.diagnostic_calibration import (
    CalibrationError,
    apply_diagnostic_calibration,
    apply_scale,
    calibration_status_line,
    contracts_from_calibration,
    load_diagnostic_calibration,
    merge_calibration_contracts,
    snapshot_diagnostic_calibration,
    validate_diagnostic_calibration,
)
from mast_freegsnke.extract import Extractor

REPO = Path(__file__).resolve().parents[1]


def test_shipped_empty_calibration_loads() -> None:
    cal = load_diagnostic_calibration(REPO / "configs" / "diagnostic_calibration.json")
    assert cal.status == "awaiting_authority"
    assert cal.n_calibrated == 0
    assert cal.n_synthesizable == 0
    rep = validate_diagnostic_calibration(cal)
    assert rep["ok"] is True
    line = calibration_status_line(path="configs/diagnostic_calibration.json", cal=cal)
    assert "awaiting diagnostic_calibration channels" in line


def test_default_config_points_at_empty_calibration() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.diagnostic_calibration_path == "configs/diagnostic_calibration.json"
    line = diagnostic_calibration_status_line(cfg, cwd=REPO)
    assert "awaiting" in line.lower()


def test_fail_closed_bad_schema(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"version": "1.0", "status": "active", "channels": {}}), encoding="utf-8")
    with pytest.raises(CalibrationError, match="non-empty channels"):
        load_diagnostic_calibration(bad)

    bad2 = tmp_path / "bad2.json"
    bad2.write_text(
        json.dumps(
            {
                "version": "1.0",
                "status": "partial",
                "channels": {
                    "X": {
                        "family": "mirnov",
                        "source_variable": "b_field_pol_probe_omv_voltage",
                        "exp_column": "110",
                        "units_in": "V",
                        "units_out": "T",
                        "scale": 0.0,
                        "sign": 1,
                        "source": "x",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CalibrationError, match="non-zero"):
        load_diagnostic_calibration(bad2)

    bad3 = tmp_path / "bad3.json"
    bad3.write_text(
        json.dumps(
            {
                "version": "1.0",
                "status": "partial",
                "channels": {
                    "S": {
                        "family": "saddle",
                        "source_variable": "b_field_tor_probe_saddle_voltage",
                        "exp_column": "A",
                        "units_in": "V",
                        "units_out": "Wb",
                        "scale": 1.0,
                        "sign": 1,
                        "synthesize": True,
                        "syn_probe": "FAKE",
                        "source": "x",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CalibrationError, match="no FreeGSNKE synthesizer"):
        load_diagnostic_calibration(bad3)


def test_apply_scale_sign_offset() -> None:
    y = np.array([1.0, 2.0, 3.0])
    out = apply_scale(y, scale=2.0, sign=-1, offset=0.5)
    np.testing.assert_allclose(out, np.array([-1.5, -3.5, -5.5]))


def test_apply_calibration_writes_production_and_contracts(tmp_path: Path) -> None:
    xr = pytest.importorskip("xarray")
    # Minimal magnetics with OMV voltage on mirnov timebase
    t = np.linspace(0.0, 1.0, 11)
    ip = np.full(11, 1.0e6)
    ds_mag = xr.Dataset(
        data_vars={
            "ip": (("time",), ip, {"units": "A"}),
            "b_field_pol_probe_omv_voltage": (
                ("b_field_pol_probe_omv_channel", "time_mirnov"),
                2.0 * np.ones((1, 5)),
                {"units": "V", "label": "Volt"},
            ),
        },
        coords={
            "time": t,
            "time_mirnov": np.linspace(0.0, 1.0, 5),
            "b_field_pol_probe_omv_channel": np.array(["110"], dtype=object),
        },
    )
    ds_pf = xr.Dataset(
        data_vars={"coil_current": (("current_channel", "time"), np.zeros((1, t.size)))},
        coords={"time": t, "current_channel": np.array(["SOL"], dtype=object)},
    )
    cache = tmp_path / "cache"
    cache.mkdir()
    ds_mag.to_zarr(cache / "magnetics.zarr", mode="w")
    ds_pf.to_zarr(cache / "pf_active.zarr", mode="w")
    inputs = tmp_path / "inputs"
    meta = Extractor(formed_plasma_frac=0.8).extract(cache, inputs)
    (inputs / "extract_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    cal_path = tmp_path / "cal.json"
    cal_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "status": "partial",
                "unit_resolution": {},
                "channels": {
                    "OMV_110": {
                        "family": "mirnov",
                        "source_variable": "b_field_pol_probe_omv_voltage",
                        "exp_column": "110",
                        "production_column": "OMV_110",
                        "units_in": "V",
                        "units_out": "T",
                        "scale": 0.01,
                        "sign": -1,
                        "offset": 0.0,
                        "synthesize": True,
                        "syn_probe": "OMV_110",
                        "source": "unit-test synthetic scale (not production metrology)",
                        "notes": "test only",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    cal = load_diagnostic_calibration(cal_path)
    assert cal.n_synthesizable == 1
    snap = snapshot_diagnostic_calibration(cal, tmp_path / "run")
    assert Path(snap["path"]).exists()
    assert snap["sha256"]

    rep = apply_diagnostic_calibration(inputs, cal)
    assert rep["ok"] is True
    assert len(rep["applied"]) == 1
    mirnov = pd.read_csv(inputs / "mirnov.csv")
    assert list(mirnov.columns) == ["time", "OMV_110"]
    # 2.0 V * 0.01 * -1 = -0.02 T
    np.testing.assert_allclose(mirnov["OMV_110"].to_numpy(), -0.02 * np.ones(5))

    contracts = contracts_from_calibration(cal)
    assert len(contracts) == 1
    assert contracts[0]["name"] == "OMV_110"
    assert contracts[0]["exp"]["csv"] == "inputs/mirnov.csv"

    # Empty calibration => no contracts merged
    empty = load_diagnostic_calibration(REPO / "configs" / "diagnostic_calibration.json")
    assert contracts_from_calibration(empty) == []


def test_synthesizer_gate_without_calibration() -> None:
    empty = load_diagnostic_calibration(REPO / "configs" / "diagnostic_calibration.json")
    assert contracts_from_calibration(empty) == []
    line = calibration_status_line(path=None)
    assert "awaiting diagnostic_calibration_path" in line


def test_unit_resolution_required_for_mismatch(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    audit = inputs / "audit_other_timebase"
    audit.mkdir(parents=True)
    pd.DataFrame({"time": [0.0, 1.0], "CC01": [1.0, 1.0]}).to_csv(
        audit / "b_field_pol_probe_cc_field.csv", index=False
    )
    (inputs / "extract_meta.json").write_text(
        json.dumps(
            {
                "probe_families": {
                    "audit_other_timebase": {
                        "variables": {
                            "b_field_pol_probe_cc_field": {"units": "T", "label": "Tesla/sec"}
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    # Channel declares units_in=T/s but no unit_resolution → fail (authoritative still T)
    cal_path = tmp_path / "cal.json"
    cal_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "status": "partial",
                "channels": {
                    "CC01": {
                        "family": "mirnov",
                        "source_variable": "b_field_pol_probe_cc_field",
                        "exp_column": "CC01",
                        "units_in": "T/s",
                        "units_out": "T/s",
                        "scale": 1.0,
                        "sign": 1,
                        "synthesize": False,
                        "source": "test",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    cal = load_diagnostic_calibration(cal_path)
    rep = apply_diagnostic_calibration(inputs, cal)
    assert rep["ok"] is False
    assert any("does not match authoritative" in e for e in rep["errors"])

    # With explicit unit_resolution → apply succeeds
    cal_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "status": "partial",
                "unit_resolution": {
                    "b_field_pol_probe_cc_field": {
                        "resolved_units": "T/s",
                        "source": "test: choose label Tesla/sec over units=T",
                    }
                },
                "channels": {
                    "CC01": {
                        "family": "mirnov",
                        "source_variable": "b_field_pol_probe_cc_field",
                        "exp_column": "CC01",
                        "units_in": "T/s",
                        "units_out": "T/s",
                        "scale": 1.0,
                        "sign": 1,
                        "synthesize": False,
                        "source": "test",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    cal2 = load_diagnostic_calibration(cal_path)
    rep2 = apply_diagnostic_calibration(inputs, cal2)
    assert rep2["ok"] is True
    assert (inputs / "mirnov.csv").exists()


def test_merge_contracts_omits_when_empty(tmp_path: Path) -> None:
    base = REPO / "configs" / "diagnostic_contracts.json"
    empty = load_diagnostic_calibration(REPO / "configs" / "diagnostic_calibration.json")
    out = tmp_path / "merged.json"
    rep = merge_calibration_contracts(base, empty, out_path=out)
    assert rep["added"] == []
    merged = json.loads(out.read_text(encoding="utf-8"))
    base_n = len(json.loads(base.read_text(encoding="utf-8"))["diagnostics"])
    assert len(merged["diagnostics"]) == base_n
