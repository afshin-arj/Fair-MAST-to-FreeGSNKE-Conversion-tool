"""Tests for science_audit (Ip residual, reconstruct quality, phases) — no invented metrology."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mast_freegsnke.science_audit import (
    build_science_audit,
    phase_timeline_from_window,
    reconstruct_quality,
    score_evolutive_ip,
)
from mast_freegsnke.certify import certify_run_dir
from mast_freegsnke.shot_summary import write_shot_expert_overlay


def test_score_evolutive_ip_rms(tmp_path: Path) -> None:
    (tmp_path / "evolutive").mkdir()
    (tmp_path / "inputs").mkdir()
    pd.DataFrame(
        {"t_abs": [0.0, 0.1, 0.2], "Ip": [1.0e6, 1.1e6, 1.0e6], "step_ok": [True, True, True]}
    ).to_csv(tmp_path / "evolutive" / "history.csv", index=False)
    pd.DataFrame({"time": [0.0, 0.1, 0.2], "ip": [1.0e6, 1.0e6, 1.0e6]}).to_csv(
        tmp_path / "inputs" / "ip.csv", index=False
    )
    rep = score_evolutive_ip(tmp_path)
    assert rep["ok"] is True
    assert rep["n"] == 3
    assert rep["rms_A"] == pytest.approx((1.0e10 / 3.0) ** 0.5)
    assert (tmp_path / "evolutive" / "ip_residual.csv").exists()


def test_reconstruct_quality_mixed_is_yellow(tmp_path: Path) -> None:
    syn = tmp_path / "synthetic"
    syn.mkdir()
    (syn / "synthetic_times.json").write_text(
        json.dumps(
            {
                "solve_mode": "mixed_inverse_and_forward_gs",
                "n_inverse_converged": 3,
                "n_forward_gs_fallback": 2,
                "n_skipped": 0,
                "n_times": 5,
                "times": [0.1, 0.2, 0.3, 0.4, 0.5],
            }
        ),
        encoding="utf-8",
    )
    rq = reconstruct_quality(tmp_path)
    assert rq["science_tier_hint"] == "yellow_mixed_or_partial"


def test_phase_timeline_from_window(tmp_path: Path) -> None:
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "window.json").write_text(
        json.dumps({"t_start": 0.2, "t_end": 0.4, "source": "test"}),
        encoding="utf-8",
    )
    ph = phase_timeline_from_window(tmp_path, pre=0.02, post=0.02)
    assert ph["available"] is True
    names = [p["phase"] for p in ph["phases"]]
    assert names == ["ramp_up", "flat_top", "ramp_down"]


def test_build_science_audit_and_summary(tmp_path: Path) -> None:
    (tmp_path / "inputs").mkdir()
    (tmp_path / "inputs" / "window.json").write_text(
        json.dumps({"t_start": 0.2, "t_end": 0.4}), encoding="utf-8"
    )
    (tmp_path / "synthetic").mkdir()
    (tmp_path / "synthetic" / "synthetic_times.json").write_text(
        json.dumps(
            {
                "solve_mode": "full_inverse",
                "n_inverse_converged": 5,
                "n_forward_gs_fallback": 0,
                "n_skipped": 0,
                "n_times": 5,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "voltage_map.resolved.json").write_text(
        json.dumps(
            {
                "circuits": {
                    "P4": {"combine": "identity", "voltage_channels": ["p4"]},
                    "P6": {
                        "combine": "from_current_ohmic",
                        "voltage_channels": [],
                        "current_circuit": "P6",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    audit = build_science_audit(tmp_path)
    assert (tmp_path / "01_summary" / "science_audit.json").exists()
    assert audit["reconstruction_quality"]["science_tier_hint"] == "green"
    assert "P6" in audit["ohmic_drive"]["ohmic_circuits"]
    assert (tmp_path / "inputs" / "phase_timeline.json").exists()

    man = {"status": "success", "blocking_errors": [], "stage_log": [], "time_window": {"t_start": 0.2, "t_end": 0.4}}
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    overlay = write_shot_expert_overlay(tmp_path, shot=30201, manifest=man, science_audit=audit)
    md = (tmp_path / overlay["summary_md"]).read_text(encoding="utf-8")
    assert "Science residuals" in md
    assert "Presentation annex" in md
    assert "from_current_ohmic" in md.lower() or "I×R" in md or "I*R" in md or "ohmic" in md.lower()


def test_certify_marks_mixed_reconstruction_yellow(tmp_path: Path) -> None:
    (tmp_path / "01_summary").mkdir(parents=True)
    (tmp_path / "provenance").mkdir()
    (tmp_path / "manifest.json").write_text(
        json.dumps({"status": "success", "blocking_errors": []}), encoding="utf-8"
    )
    (tmp_path / "01_summary" / "science_audit.json").write_text(
        json.dumps(
            {
                "reconstruction_quality": {"science_tier_hint": "yellow_mixed_or_partial"},
                "evolutive_ip": {"ok": False},
                "passive_resistivity": {"status": "awaiting_authority"},
            }
        ),
        encoding="utf-8",
    )
    rep = certify_run_dir(tmp_path, skip_replay=True, skip_reviewer_pack=True)
    assert rep["tier"] == "YELLOW"
    assert any("reconstruction_quality" in w for w in rep["warnings"])
    assert any("passive_resistivity" in w for w in rep["warnings"])
