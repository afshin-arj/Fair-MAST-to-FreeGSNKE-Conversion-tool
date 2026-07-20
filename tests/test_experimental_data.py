"""experimental_data pack: categorized CSV + portable plots."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mast_freegsnke.config import AppConfig
from mast_freegsnke.experimental_data import build_experimental_data


REPO = Path(__file__).resolve().parents[1]


def _seed_inputs(run_dir: Path) -> None:
    inputs = run_dir / "inputs"
    inputs.mkdir(parents=True)
    t = [0.0, 0.1, 0.2, 0.3]
    pd.DataFrame({"time": t, "ip": [1e5, 2e5, 8e5, 7e5]}).to_csv(inputs / "ip.csv", index=False)
    pd.DataFrame(
        {"time": t, "P2IL FEED": [1, 2, 3, 4], "P2IU FEED": [1, 2, 3, 4], "SOL": [10, 11, 12, 13]}
    ).to_csv(inputs / "pf_active_raw.csv", index=False)
    pd.DataFrame(
        {
            "time": t,
            "P2_inner": [1, 2, 3, 4],
            "P2_outer": [1, 2, 3, 4],
            "P3": [0, 0, 0, 0],
            "P4": [-1, -2, -3, -4],
            "P5": [-1, -2, -3, -4],
            "P6": [-5, -6, -7, -8],
            "Solenoid": [10, 11, 12, 13],
        }
    ).to_csv(inputs / "pf_currents.csv", index=False)
    pd.DataFrame({"time": t, "p1": [1, 2, 3, 4], "p2": [1, 1, 1, 1]}).to_csv(
        inputs / "pf_voltages_raw.csv", index=False
    )
    pd.DataFrame(
        {"time": t, "Solenoid": [1, 2, 3, 4], "P2_inner": [1, 1, 1, 1], "P6": [0.1, 0.2, 0.3, 0.4]}
    ).to_csv(inputs / "pf_voltages.csv", index=False)
    pd.DataFrame({"time": t, "CC03": [0.1, 0.2, 0.2, 0.1], "CC04": [0.05, 0.06, 0.07, 0.06]}).to_csv(
        inputs / "flux_loops.csv", index=False
    )
    pd.DataFrame(
        {
            "time": t,
            "CCBV01": [0.01, 0.02, 0.02, 0.01],
            "OBV01": [0.01, 0.01, 0.02, 0.01],
            "OBR01": [0.0, 0.01, 0.01, 0.0],
        }
    ).to_csv(inputs / "pickups.csv", index=False)
    audit = inputs / "audit_other_timebase"
    audit.mkdir()
    pd.DataFrame({"time": t, "201": [0.1, 0.2, 0.3, 0.2]}).to_csv(
        audit / "b_field_pol_probe_omv_voltage.csv", index=False
    )
    (inputs / "window.json").write_text(
        json.dumps({"t_start": 0.1, "t_end": 0.25}) + "\n", encoding="utf-8"
    )


def test_build_experimental_data_creates_pack(tmp_path: Path) -> None:
    run_dir = tmp_path / "SHOT" / "30201"
    _seed_inputs(run_dir)
    machine = tmp_path / "machine_authority"
    machine.mkdir()
    (machine / "coil_geometry.json").write_text(
        json.dumps({"Solenoid": {"R": 0.2, "Z": 0.0}}) + "\n", encoding="utf-8"
    )
    (REPO / "configs" / "l1_voltage_inventory_30201.json").exists()

    rep = build_experimental_data(
        run_dir,
        shot=30201,
        cache_dir=None,
        machine_dir=machine,
        repo_root=REPO,
        include_l1=True,
        include_l3=True,
        plots=True,
    )
    assert rep.ok, rep.errors
    root = run_dir / "experimental_data"
    assert (root / "00_index" / "catalog.json").exists()
    assert (root / "01_plasma" / "ip.csv").exists()
    assert (root / "02_pf" / "currents_circuits.csv").exists()
    assert (root / "03_magnetics" / "flux_loops.csv").exists()
    assert (root / "03_magnetics" / "audit_other_timebase" / "b_field_pol_probe_omv_voltage.csv").exists()
    assert (root / "l1" / "STATUS.json").exists()
    assert (root / "l3" / "STATUS.json").exists()
    cat = json.loads((root / "00_index" / "catalog.json").read_text(encoding="utf-8"))
    assert cat["shot"] == 30201
    assert cat["families"]["plasma_ip"]["kind"] == "measured"
    assert cat["families"]["currents_circuits"]["kind"] == "derived"
    assert cat["families"]["audit_other_timebase"]["kind"] == "audit_uncalibrated"
    # Plots are portable Agg; require at least plasma plot when matplotlib present
    assert (root / "05_plots" / "01_plasma_ip.png").exists()
    assert (root / "05_plots" / "02_pf_currents_circuits.png").exists()


def test_build_experimental_data_missing_inputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "empty"
    run_dir.mkdir()
    rep = build_experimental_data(run_dir, shot=1, plots=False)
    assert rep.ok is False
    assert "inputs_dir_missing" in rep.errors


def test_default_config_enables_experimental_data() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.enable_experimental_data is True
    assert cfg.experimental_data_plots is True
    assert cfg.experimental_data_include_l1 is True
    assert cfg.experimental_data_include_l3 is True


def test_paths_use_forward_slash_in_catalog(tmp_path: Path) -> None:
    """Catalog paths must be portable (no backslash-only Windows forms required)."""
    run_dir = tmp_path / "SHOT" / "1"
    _seed_inputs(run_dir)
    rep = build_experimental_data(run_dir, shot=1, plots=False, include_l1=False, include_l3=False)
    assert rep.ok
    cat = json.loads((run_dir / "experimental_data" / "00_index" / "catalog.json").read_text(encoding="utf-8"))
    path = cat["families"]["plasma_ip"]["path"]
    assert "\\" not in path
    assert path.startswith("experimental_data/")
