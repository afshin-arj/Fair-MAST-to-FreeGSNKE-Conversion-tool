"""Tests for real contract-driven residual metrics (v10.3.0).

Covers:
  - per-probe 2-D extraction into family CSVs
  - synthetic CSV schema expected by contracts
  - validation of the shipped configs/diagnostic_contracts.json
  - metrics end-to-end on small fixture data (exp interpolated onto syn times)
"""

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
from mast_freegsnke.extract import Extractor
from mast_freegsnke.metrics import compare_from_contracts
from mast_freegsnke.synthetic_extract import extract_synthetic_by_contracts

REPO = Path(__file__).resolve().parents[1]


def _write_2d_zarr(path: Path) -> None:
    """Minimal FAIR-MAST-shaped magnetics + pf_active zarr for Extractor tests."""
    xr = pytest.importorskip("xarray")
    t = np.linspace(0.0, 1.0, 21)
    # Formed-plasma selection needs a rising then flat Ip
    ip = np.concatenate([np.linspace(0.0, 1.0e6, 11), np.full(10, 1.0e6)])
    fl_ch = np.array(["CC03", "P3L/4"], dtype=object)
    pu_ch = np.array(["CCBV01", "OBV01"], dtype=object)
    fl = np.vstack([0.1 + 0.01 * np.sin(2 * np.pi * t), 0.2 + 0.02 * np.cos(2 * np.pi * t)])
    pu = np.vstack([0.01 * np.ones_like(t), -0.02 * np.ones_like(t)])

    ds_mag = xr.Dataset(
        data_vars={
            "ip": (("time",), ip, {"units": "A"}),
            "flux_loop_flux": (("flux_loop_channel", "time"), fl, {"units": "Wb"}),
            "b_field_pol_probe_ccbv_field": (
                ("b_field_pol_probe_ccbv_channel", "time"),
                pu[:1],
                {"units": "T"},
            ),
            "b_field_pol_probe_obv_field": (
                ("b_field_pol_probe_obv_channel", "time"),
                pu[1:],
                {"units": "T"},
            ),
            # Different timebase: must be skipped from contracts, but extracted
            # verbatim for audit with evidence-based exclusion reasons.
            "b_field_pol_probe_cc_field": (
                ("b_field_pol_probe_cc_channel", "time_mirnov"),
                np.ones((1, 5)),
                {"units": "T", "label": "Tesla/sec", "uda_name": "xmc/CC/MV/201"},
            ),
            "b_field_pol_probe_omv_voltage": (
                ("b_field_pol_probe_omv_channel", "time_mirnov"),
                2.0 * np.ones((1, 5)),
                {"units": "V", "label": "Volt", "uda_name": "xmc/OMV/110"},
            ),
        },
        coords={
            "time": t,
            "time_mirnov": np.linspace(0.0, 1.0, 5),
            "flux_loop_channel": fl_ch,
            "b_field_pol_probe_ccbv_channel": pu_ch[:1],
            "b_field_pol_probe_obv_channel": pu_ch[1:],
            "b_field_pol_probe_cc_channel": np.array(["CC01"], dtype=object),
            "b_field_pol_probe_omv_channel": np.array(["110"], dtype=object),
        },
    )
    ds_pf = xr.Dataset(
        data_vars={"coil_current": (("current_channel", "time"), np.zeros((1, t.size)))},
        coords={"time": t, "current_channel": np.array(["SOL"], dtype=object)},
    )
    path.mkdir(parents=True, exist_ok=True)
    ds_mag.to_zarr(path / "magnetics.zarr", mode="w")
    ds_pf.to_zarr(path / "pf_active.zarr", mode="w")


def test_extract_per_probe_family_csvs(tmp_path: Path) -> None:
    cache = tmp_path / "shot_cache"
    out = tmp_path / "inputs"
    _write_2d_zarr(cache)

    meta = Extractor(formed_plasma_frac=0.8).extract(cache, out)
    fl = pd.read_csv(out / "flux_loops.csv")
    pu = pd.read_csv(out / "pickups.csv")

    assert list(fl.columns[:1]) == ["time"]
    assert "CC03" in fl.columns and "P3L/4" in fl.columns
    assert "CCBV01" in pu.columns and "OBV01" in pu.columns
    np.testing.assert_allclose(fl["CC03"].to_numpy(), 0.1 + 0.01 * np.sin(2 * np.pi * fl["time"].to_numpy()))

    fam = meta["probe_families"]
    assert fam["families"]["flux_loops"]["variables"]["flux_loop_flux"]["units"] == "Wb"
    assert fam["families"]["pickups"]["variables"]["b_field_pol_probe_ccbv_field"]["units"] == "T"
    skipped = {s["var"] for s in fam["skipped_2d_vars"]}
    assert "b_field_pol_probe_cc_field" in skipped


def test_synthetic_csv_schema_matches_contracts(tmp_path: Path) -> None:
    """Runner-emitted synthetic CSVs must have time + probe-name columns."""
    syn = tmp_path / "synthetic"
    syn.mkdir()
    t0 = 0.25
    pd.DataFrame([[t0, 0.11, 0.22]], columns=["time", "FL_CC03", "FL_P3L_4"]).to_csv(
        syn / "synthetic_fluxloops.csv", index=False
    )
    pd.DataFrame([[t0, 0.01, -0.02]], columns=["time", "CCBV01", "OBV01"]).to_csv(
        syn / "synthetic_pickups.csv", index=False
    )
    fl = pd.read_csv(syn / "synthetic_fluxloops.csv")
    pu = pd.read_csv(syn / "synthetic_pickups.csv")
    assert fl.shape == (1, 3) and pu.shape == (1, 3)
    assert fl.loc[0, "time"] == t0
    assert set(fl.columns) == {"time", "FL_CC03", "FL_P3L_4"}
    assert set(pu.columns) == {"time", "CCBV01", "OBV01"}


def test_shipped_diagnostic_contracts_validate() -> None:
    path = REPO / "configs" / "diagnostic_contracts.json"
    assert path.exists(), "shipped contracts authority missing"
    contracts = load_contracts(path, base_dir=REPO)
    # Schema / identity only (files are run-scoped, so require_files=False here).
    rep = validate_contracts(contracts, require_files=False)
    assert rep["ok"], rep["errors"]
    # v10.4.0: ALL identity-mapped channels contracted (no per-shot NaN exclusions):
    # 15 flux loops + 40 CCBV + 19 OBV + 19 OBR pickups.
    assert rep["n"] == 93
    names = {c.name for c in contracts}
    # Channels that are all-NaN on reference shot 30201 must now be contracted
    # (they are skipped shot-scoped at metrics time, not hard-excluded).
    for previously_excluded in ["FL_P3L_4", "CCBV02", "CCBV21", "CCBV32", "CCBV35", "OBV01", "OBR02", "OBR19"]:
        assert previously_excluded in names, f"{previously_excluded} must be contracted"
    dtypes = {c.dtype for c in contracts}
    assert dtypes == {"flux_loop", "pickup"}
    units = {c.units for c in contracts}
    assert units == {"Wb", "T"}
    for c in contracts:
        assert c.exp.sign == 1.0 and c.exp.scale == 1.0
        assert c.syn.sign == 1.0 and c.syn.scale == 1.0
        assert c.exp.csv.name in {"flux_loops.csv", "pickups.csv"}
        assert c.syn.csv.name in {"synthetic_fluxloops.csv", "synthetic_pickups.csv"}


def test_metrics_e2e_exp_interp_onto_syn_time(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "synthetic").mkdir()

    t = np.linspace(0.0, 1.0, 21)
    y = 0.1 + 0.05 * t
    pd.DataFrame({"time": t, "CC03": y}).to_csv(run_dir / "inputs" / "flux_loops.csv", index=False)
    # Single solved slice at t=0.5; synthetic deliberately offset by +0.01 Wb
    t0 = 0.5
    y_exp_at_t0 = float(np.interp(t0, t, y))
    pd.DataFrame({"time": [t0], "FL_CC03": [y_exp_at_t0 + 0.01]}).to_csv(
        run_dir / "synthetic" / "synthetic_fluxloops.csv", index=False
    )

    contracts_json = tmp_path / "contracts.json"
    contracts_json.write_text(
        json.dumps(
            {
                "version": "1.0",
                "diagnostics": [
                    {
                        "name": "FL_CC03",
                        "dtype": "flux_loop",
                        "units": "Wb",
                        "exp": {
                            "csv": "inputs/flux_loops.csv",
                            "time_col": "time",
                            "value_col": "CC03",
                            "scale": 1.0,
                            "sign": 1.0,
                        },
                        "syn": {
                            "csv": "synthetic/synthetic_fluxloops.csv",
                            "time_col": "time",
                            "value_col": "FL_CC03",
                            "scale": 1.0,
                            "sign": 1.0,
                        },
                    }
                ],
            }
        )
    )
    contracts = resolve_contracts_for_run(contracts_json, run_dir)
    assert validate_contracts(contracts, require_files=True)["ok"]

    syn_res = extract_synthetic_by_contracts(run_dir, contracts)
    assert syn_res.ok

    met = compare_from_contracts(run_dir, contracts)
    assert met["ok"] and met["n_scored"] == 1
    row = met["per_contract"][0]
    assert row["n"] == 1
    assert abs(row["rms"] - 0.01) < 1e-12
    assert abs(row["mae"] - 0.01) < 1e-12
    assert (run_dir / "metrics" / "reconstruction_metrics.json").exists()
    assert (run_dir / "metrics" / "residual_FL_CC03.csv").exists()


def test_metrics_refuses_extrapolation(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "synthetic").mkdir()
    pd.DataFrame({"time": [0.0, 0.5, 1.0], "CC03": [0.1, 0.2, 0.3]}).to_csv(
        run_dir / "inputs" / "flux_loops.csv", index=False
    )
    pd.DataFrame({"time": [1.5], "FL_CC03": [0.4]}).to_csv(
        run_dir / "synthetic" / "synthetic_fluxloops.csv", index=False
    )
    contracts_json = tmp_path / "c.json"
    contracts_json.write_text(
        json.dumps(
            {
                "version": "1.0",
                "diagnostics": [
                    {
                        "name": "FL_CC03",
                        "dtype": "flux_loop",
                        "units": "Wb",
                        "exp": {
                            "csv": "inputs/flux_loops.csv",
                            "time_col": "time",
                            "value_col": "CC03",
                        },
                        "syn": {
                            "csv": "synthetic/synthetic_fluxloops.csv",
                            "time_col": "time",
                            "value_col": "FL_CC03",
                        },
                    }
                ],
            }
        )
    )
    contracts = resolve_contracts_for_run(contracts_json, run_dir)
    met = compare_from_contracts(run_dir, contracts)
    assert not met["ok"]
    assert met["n_scored"] == 0
    assert any("outside experimental support" in e for e in met["errors"])


def _contract_entry(name: str, exp_col: str) -> dict:
    return {
        "name": name,
        "dtype": "flux_loop",
        "units": "Wb",
        "exp": {"csv": "inputs/flux_loops.csv", "time_col": "time", "value_col": exp_col},
        "syn": {"csv": "synthetic/synthetic_fluxloops.csv", "time_col": "time", "value_col": name},
    }


def test_metrics_skip_all_nan_channel_shot_scoped(tmp_path: Path) -> None:
    """All-NaN experimental channel -> skipped_all_nan, NOT a failure (v10.4.0).

    Channels with real data must still score, and the summary must stay ok.
    """
    run_dir = tmp_path / "run"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "synthetic").mkdir()

    t = np.linspace(0.0, 1.0, 21)
    pd.DataFrame({
        "time": t,
        "CC03": 0.1 + 0.05 * t,          # real data
        "P3L/4": np.full_like(t, np.nan),  # all-NaN on this shot
    }).to_csv(run_dir / "inputs" / "flux_loops.csv", index=False)

    t0 = 0.5
    pd.DataFrame({
        "time": [t0],
        "FL_CC03": [float(np.interp(t0, t, 0.1 + 0.05 * t)) + 0.01],
        "FL_P3L_4": [0.2],
    }).to_csv(run_dir / "synthetic" / "synthetic_fluxloops.csv", index=False)

    contracts_json = tmp_path / "contracts.json"
    contracts_json.write_text(json.dumps({
        "version": "1.0",
        "diagnostics": [_contract_entry("FL_CC03", "CC03"), _contract_entry("FL_P3L_4", "P3L/4")],
    }))
    contracts = resolve_contracts_for_run(contracts_json, run_dir)

    met = compare_from_contracts(run_dir, contracts)
    assert met["ok"], met["errors"]
    assert met["n_scored"] == 1
    assert met["n_skipped_all_nan"] == 1
    assert met["errors"] == []
    (skip,) = met["skipped"]
    assert skip["name"] == "FL_P3L_4"
    assert skip["status"] == "skipped_all_nan"
    assert skip["n_finite_experimental"] == 0
    # Never fabricate a residual for the skipped channel.
    assert not (run_dir / "metrics" / "residual_FL_P3L_4.csv").exists()
    saved = json.loads((run_dir / "metrics" / "reconstruction_metrics.json").read_text())
    assert saved["n_skipped_all_nan"] == 1


def test_metrics_multi_time_scoring(tmp_path: Path) -> None:
    """Residuals are scored across ALL synthetic sample times (v10.4.0)."""
    run_dir = tmp_path / "run"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "synthetic").mkdir()

    t = np.linspace(0.0, 1.0, 101)
    y = 0.1 + 0.05 * t
    pd.DataFrame({"time": t, "CC03": y}).to_csv(run_dir / "inputs" / "flux_loops.csv", index=False)

    times = np.linspace(0.2, 0.8, 5)
    offsets = np.array([0.01, -0.02, 0.03, -0.01, 0.02])
    syn_vals = np.interp(times, t, y) + offsets
    pd.DataFrame({"time": times, "FL_CC03": syn_vals}).to_csv(
        run_dir / "synthetic" / "synthetic_fluxloops.csv", index=False
    )
    (run_dir / "synthetic" / "synthetic_times.json").write_text(json.dumps({
        "rule": "linspace_window_inclusive",
        "n_times": 5,
        "t_start": 0.2,
        "t_end": 0.8,
        "times": [float(x) for x in times],
    }))

    contracts_json = tmp_path / "contracts.json"
    contracts_json.write_text(json.dumps({
        "version": "1.0",
        "diagnostics": [_contract_entry("FL_CC03", "CC03")],
    }))
    contracts = resolve_contracts_for_run(contracts_json, run_dir)

    met = compare_from_contracts(run_dir, contracts)
    assert met["ok"], met["errors"]
    row = met["per_contract"][0]
    assert row["n"] == 5
    expected_rms = float(np.sqrt(np.mean(offsets**2)))
    assert abs(row["rms"] - expected_rms) < 1e-9
    assert abs(row["mae"] - float(np.mean(np.abs(offsets)))) < 1e-9
    assert abs(row["max_abs"] - 0.03) < 1e-9
    # The scored times + selection rule must be recorded in the summary.
    tb = met["synthetic_timebase"]
    assert tb["rule"] == "linspace_window_inclusive"
    assert tb["n_times"] == 5
    res = pd.read_csv(run_dir / "metrics" / "residual_FL_CC03.csv")
    assert len(res) == 5


def test_extract_audit_other_timebase_families(tmp_path: Path) -> None:
    """Other-timebase families extracted verbatim for audit with evidence (v10.4.0)."""
    cache = tmp_path / "shot_cache"
    out = tmp_path / "inputs"
    _write_2d_zarr(cache)

    meta = Extractor(formed_plasma_frac=0.8).extract(cache, out)
    audit = meta["probe_families"]["audit_other_timebase"]
    variables = audit["variables"]
    assert set(variables) == {"b_field_pol_probe_cc_field", "b_field_pol_probe_omv_voltage"}

    # Mirnov field: units/label contradiction is explicit evidence.
    cc = variables["b_field_pol_probe_cc_field"]
    assert cc["units"] == "T" and cc["label"] == "Tesla/sec"
    assert cc["timebase"] == "time_mirnov"
    assert any("unit_metadata_contradiction" in r for r in cc["contract_exclusion_reasons"])
    assert any("awaiting_optional_diagnostic_calibration" in r for r in cc["contract_exclusion_reasons"])
    assert any("freegsnke_point_pickup_synth_gated" in r for r in cc["contract_exclusion_reasons"])

    # OMV voltage: raw volts, no published calibration.
    omv = variables["b_field_pol_probe_omv_voltage"]
    assert omv["units"] == "V"
    assert any("raw_voltage_units_V" in r for r in omv["contract_exclusion_reasons"])
    assert any("awaiting_optional_diagnostic_calibration" in r for r in omv["contract_exclusion_reasons"])

    # Traces written verbatim on the native timebase, channel names verbatim.
    cc_df = pd.read_csv(out / "audit_other_timebase" / "b_field_pol_probe_cc_field.csv")
    assert list(cc_df.columns) == ["time", "CC01"]
    assert len(cc_df) == 5
    np.testing.assert_allclose(cc_df["CC01"].to_numpy(), np.ones(5))
    omv_df = pd.read_csv(out / "audit_other_timebase" / "b_field_pol_probe_omv_voltage.csv")
    assert list(omv_df.columns) == ["time", "110"]
    np.testing.assert_allclose(omv_df["110"].to_numpy(), 2.0 * np.ones(5))


def test_execution_authority_metrics_timebase(tmp_path: Path) -> None:
    """metrics_timebase is a first-class execution authority (v10.4.0)."""
    import pytest as _pytest

    from mast_freegsnke.execution_authority import (
        MetricsTimebaseSpec,
        load_execution_authority_bundle,
        write_execution_authority,
    )

    root = write_execution_authority(tmp_path, metrics_n_times=7)
    assert (root / "metrics_timebase_authority.json").exists()
    bundle = load_execution_authority_bundle(root / "execution_authority_bundle.json")
    assert bundle.metrics_timebase.rule == "linspace_window_inclusive"
    assert bundle.metrics_timebase.n_times == 7

    with _pytest.raises(ValueError, match="n_times"):
        MetricsTimebaseSpec(n_times=0).validate()
    with _pytest.raises(ValueError, match="rule"):
        MetricsTimebaseSpec(rule="random_times").validate()
