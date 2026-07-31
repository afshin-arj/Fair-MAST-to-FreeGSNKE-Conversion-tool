"""Evolutive rethink v11.31: measured_pf default + clamp tautology + Raxis drift."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mast_freegsnke.evolutive_authority import load_evolutive_authority
from mast_freegsnke.science_audit import (
    build_science_audit,
    score_evolutive_ip,
    score_evolutive_raxis_drift,
)
from mast_freegsnke.shot_summary import write_shot_expert_overlay

REPO = Path(__file__).resolve().parents[1]


def test_evolutive_authority_default_measured_pf() -> None:
    ea = load_evolutive_authority(REPO / "configs" / "evolutive_authority.json")
    assert ea.ic_coil_currents == "measured_pf"
    assert ea.authority_version == "11.31.0"


def test_score_evolutive_ip_clamp_tautology(tmp_path: Path) -> None:
    evo = tmp_path / "03_reconstruction" / "evolutive"
    evo.mkdir(parents=True)
    (tmp_path / "inputs").mkdir()
    pd.DataFrame(
        {
            "t_abs": [0.20, 0.21, 0.22],
            "Ip": [1.0e6, 1.0e6, 1.0e6],
            "Raxis": [0.90, 0.95, 1.05],
            "Zaxis": [0.0, 0.01, 0.02],
            "step_ok": [True, True, True],
        }
    ).to_csv(evo / "history.csv", index=False)
    pd.DataFrame({"time": [0.20, 0.21, 0.22], "ip": [1.0e6, 1.0e6, 1.0e6]}).to_csv(
        tmp_path / "inputs" / "ip.csv", index=False
    )
    (evo / "evolutive_meta.json").write_text(
        json.dumps(
            {
                "clamp_ip_to_measured": True,
                "ic_coil_currents": "measured_pf",
                "n_passive": 0,
                "n_steps_requested": 18,
                "n_steps_recorded": 3,
                "early_stop": "axis_drift",
                "abort_when_axis_drift_m": 0.12,
                "early_stop_detail": {
                    "t_abs": 0.22,
                    "step": 2,
                    "Raxis": 1.05,
                    "Zaxis": 0.02,
                    "Raxis0": 0.90,
                    "Zaxis0": 0.0,
                    "drift_m": 0.151,
                    "threshold_m": 0.12,
                },
            }
        ),
        encoding="utf-8",
    )
    ip = score_evolutive_ip(tmp_path)
    assert ip["ok"] is True
    assert ip["status"] == "clamp_tautology"
    assert ip["clamp_ip_to_measured"] is True
    assert ip["early_stop"] == "axis_drift"
    assert "by construction" in str(ip.get("note", "")).lower()

    ax = score_evolutive_raxis_drift(tmp_path)
    assert ax["ok"] is True
    assert ax["status"] == "early_stop_axis_drift"
    assert ax["max_drift_m"] == pytest.approx((0.15**2 + 0.02**2) ** 0.5)
    assert ax["early_stop_drift_m"] == pytest.approx(0.151)
    assert (evo / "raxis_drift.csv").exists()

    audit = build_science_audit(tmp_path)
    assert audit["version"] == "1.5"
    assert audit["evolutive_ip"]["status"] == "clamp_tautology"
    assert audit["evolutive_raxis_drift"]["ok"] is True
    adv = audit["presentation_advisories"]
    blob = " ".join(adv.get("items") or [])
    assert "clamp tautology" in blob.lower() or "clamp_ip" in blob.lower()
    assert "axis_drift" in blob

    write_shot_expert_overlay(tmp_path, shot=30201, manifest={"status": "ok"})
    summary = (tmp_path / "01_summary" / "SUMMARY.md").read_text(encoding="utf-8")
    assert "clamp_tautology" in summary
    assert "Raxis drift" in summary


def test_score_evolutive_ip_without_clamp_is_ok(tmp_path: Path) -> None:
    evo = tmp_path / "evolutive"
    evo.mkdir()
    (tmp_path / "inputs").mkdir()
    pd.DataFrame(
        {"t_abs": [0.0, 0.1], "Ip": [1.0e6, 1.1e6], "step_ok": [True, True]}
    ).to_csv(evo / "history.csv", index=False)
    pd.DataFrame({"time": [0.0, 0.1], "ip": [1.0e6, 1.0e6]}).to_csv(
        tmp_path / "inputs" / "ip.csv", index=False
    )
    (evo / "evolutive_meta.json").write_text(
        json.dumps({"clamp_ip_to_measured": False}), encoding="utf-8"
    )
    rep = score_evolutive_ip(tmp_path)
    assert rep["ok"] is True
    assert rep["status"] == "ok"
    assert rep["clamp_ip_to_measured"] is False


def test_evolutive_template_soft_stop_before_snapshot() -> None:
    text = (REPO / "templates" / "evolutive_run.py.tpl").read_text(encoding="utf-8")
    assert 'ic_coil_currents", "measured_pf"' in text or 'get("ic_coil_currents", "measured_pf")' in text
    soft = text.find("Soft-stops BEFORE snapshot")
    snap = text.find("if snap_every > 0 and (step % snap_every == 0):")
    assert 0 < soft < snap
    assert "early_stop={early_stop}" in text or "[early_stop=" in text
    assert "clamp_ip (Ip residual tautology)" in text
