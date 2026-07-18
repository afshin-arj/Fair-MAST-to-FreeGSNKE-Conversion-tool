"""v11.0.0: voltage extract/map, evolutive template, SHOT layout, summary overlay."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mast_freegsnke.config import AppConfig, run_dir_for_shot
from mast_freegsnke.evolutive_authority import load_evolutive_authority
from mast_freegsnke.generate import ScriptGenerator
from mast_freegsnke.shot_summary import write_shot_expert_overlay
from mast_freegsnke.voltage_map import (
    apply_voltage_map,
    load_voltage_map,
    validate_voltage_map,
)

REPO = Path(__file__).resolve().parents[1]


def test_shipped_voltage_map_valid() -> None:
    vmap = load_voltage_map(REPO / "configs" / "voltage_map.json")
    rep = validate_voltage_map(vmap)
    assert rep["ok"], rep["errors"]
    assert "Solenoid" in vmap.circuits
    assert vmap.circuits["Solenoid"]["voltage_channels"] == ["p1"]
    assert vmap.circuits["P6"]["combine"] == "default"
    assert float(vmap.circuits["P6"]["default_V"]) == 0.0


def test_voltage_map_fail_closed_missing_default_v(tmp_path: Path) -> None:
    bad = {
        "version": "1.0",
        "machine_active_circuit_order": ["Solenoid"],
        "circuits": {
            "Solenoid": {
                "voltage_channels": [],
                "combine": "default",
                "notes": "missing default_V on purpose",
            }
        },
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    vmap = load_voltage_map(p)
    rep = validate_voltage_map(vmap)
    assert not rep["ok"]
    assert any("default_V" in e for e in rep["errors"])


def test_apply_voltage_map_writes_circuit_columns(tmp_path: Path) -> None:
    raw = tmp_path / "pf_voltages_raw.csv"
    pd.DataFrame(
        {
            "time": [0.0, 0.1],
            "p1": [1.0, 2.0],
            "p2": [3.0, 4.0],
            "p4": [5.0, 6.0],
            "p5": [7.0, 8.0],
        }
    ).to_csv(raw, index=False)
    vmap = load_voltage_map(REPO / "configs" / "voltage_map.json")
    out = tmp_path / "pf_voltages.csv"
    rep = apply_voltage_map(raw, out, vmap)
    assert rep["ok"], rep["errors"]
    df = pd.read_csv(out)
    for name in vmap.machine_active_circuit_order:
        assert name in df.columns
    assert list(df["Solenoid"]) == pytest.approx([1.0, 2.0])
    assert list(df["PX"]) == pytest.approx([3.0, 4.0])
    assert list(df["P6"]) == pytest.approx([0.0, 0.0])


def test_apply_voltage_map_allows_sparse_nan(tmp_path: Path) -> None:
    raw = tmp_path / "pf_voltages_raw.csv"
    pd.DataFrame(
        {
            "time": [0.0, 0.1, 0.2],
            "p1": [1.0, float("nan"), 3.0],
            "p2": [3.0, 4.0, 5.0],
            "p4": [5.0, 6.0, 7.0],
            "p5": [7.0, 8.0, 9.0],
        }
    ).to_csv(raw, index=False)
    vmap = load_voltage_map(REPO / "configs" / "voltage_map.json")
    out = tmp_path / "pf_voltages.csv"
    rep = apply_voltage_map(raw, out, vmap)
    assert rep["ok"], rep["errors"]
    assert rep["circuits"]["Solenoid"]["n_nonfinite"] == 1
    assert rep["circuits"]["Solenoid"]["n_finite"] == 2


def test_apply_voltage_map_fails_if_all_nan(tmp_path: Path) -> None:
    raw = tmp_path / "pf_voltages_raw.csv"
    pd.DataFrame(
        {
            "time": [0.0, 0.1],
            "p1": [float("nan"), float("nan")],
            "p2": [3.0, 4.0],
            "p4": [5.0, 6.0],
            "p5": [7.0, 8.0],
        }
    ).to_csv(raw, index=False)
    vmap = load_voltage_map(REPO / "configs" / "voltage_map.json")
    out = tmp_path / "pf_voltages.csv"
    rep = apply_voltage_map(raw, out, vmap)
    assert not rep["ok"]
    assert any("insufficient_finite_voltage_samples:Solenoid" in e for e in rep["errors"])


def test_evolutive_authority_shipped() -> None:
    ea = load_evolutive_authority(REPO / "configs" / "evolutive_authority.json")
    assert ea.n_steps >= 1
    assert ea.full_timestep_s > 0
    assert ea.plasma_resistivity_ohm_m > 0


def test_evolutive_template_present_and_renders(tmp_path: Path) -> None:
    tpl = REPO / "templates" / "evolutive_run.py.tpl"
    assert tpl.exists()
    text = tpl.read_text(encoding="utf-8")
    assert "nl_solver" in text
    assert "initialize_from_ICs" in text
    assert "nlstepper" in text
    assert "active_voltage_vec" in text
    gen = ScriptGenerator(templates_dir=REPO / "templates")
    gen.generate(run_dir=tmp_path, machine_dir=tmp_path / "machine", formed_frac=0.8)
    evo = (tmp_path / "evolutive_run.py").read_text(encoding="utf-8")
    assert "__MACHINE_DIR_REPR__" not in evo
    assert "nonlinear_solve" in evo


def test_default_runs_dir_is_shot() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.runs_dir == Path("SHOT")
    assert cfg.execute_evolutive is True
    assert cfg.voltage_map_path
    assert cfg.evolutive_authority_path
    assert run_dir_for_shot(cfg, 30201) == Path("SHOT") / "30201"


def test_shot_expert_overlay(tmp_path: Path) -> None:
    run_dir = tmp_path / "SHOT" / "30201"
    run_dir.mkdir(parents=True)
    manifest = {
        "status": "success",
        "created_utc": "2026-07-18T00:00:00Z",
        "time_window": {"t_start": 0.2, "t_end": 0.4},
        "freegsnke_execution": {
            "results": [
                {"script": "inverse_run.py", "ok": True},
                {"script": "forward_run.py", "ok": True},
                {"script": "evolutive_run.py", "ok": True},
            ]
        },
        "reconstruction_metrics": {"ok": True, "n_scored": 10, "n_skipped_all_nan": 0},
        "blocking_errors": [],
        "stage_log": [{"stage": "extract_csv", "ok": True}],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    paths = write_shot_expert_overlay(run_dir, shot=30201, manifest=manifest)
    assert (run_dir / paths["readme"]).exists()
    assert (run_dir / paths["summary_md"]).exists()
    assert (run_dir / paths["summary_json"]).exists()
    assert (run_dir / paths["timeline"]).exists()
    readme = (run_dir / "00_README.txt").read_text(encoding="utf-8")
    assert "inputs/" in readme
    assert "manifest.json" in readme
