"""Tests for science_audit (Ip residual, reconstruct quality, phases) — no invented metrology."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mast_freegsnke.science_audit import (
    build_science_audit,
    evolutive_science_kpis,
    forward_gate_summary,
    passives_ab_readiness,
    phase_timeline_from_window,
    publish_claims_table,
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


def test_forward_gate_not_inverse_dn_peer(tmp_path: Path) -> None:
    pres = tmp_path / "presentation"
    pres.mkdir()
    (pres / "forward_times.json").write_text(
        json.dumps(
            {
                "n_ok": 3,
                "n_converged": 2,
                "n_completed_max_iter": 1,
                "n_skipped": 0,
                "n_times": 3,
                "window_currents": "measured_pf",
                "ic_psi_used": True,
                "profile_source_requested": "profile_trajectory_if_ok",
                "profile_sources_used": ["profile_trajectory_authority"],
                "per_time": [
                    {"status": "converged"},
                    {"status": "converged"},
                    {"status": "completed_max_iter"},
                ],
            }
        ),
        encoding="utf-8",
    )
    fwd = forward_gate_summary(tmp_path)
    assert fwd["available"] is True
    assert fwd["not_inverse_dn_peer"] is True
    assert fwd["demo_mode"] is False
    assert fwd["science_role"] == "measured_pf_static_gs_plant_check"
    assert "plant" in str(fwd.get("publish_as", "")).lower() or "not" in str(
        fwd.get("publish_as", "")
    ).lower()
    claims = publish_claims_table(tmp_path)
    products = {r["product"] for r in claims["rows"]}
    assert products >= {"Inverse", "Forward", "Evolutive", "EFIT archive compare"}
    fwd_row = next(r for r in claims["rows"] if r["product"] == "Forward")
    assert fwd_row["not_inverse_dn_peer"] is True


def test_forward_gate_demo_mode_dump_currents(tmp_path: Path) -> None:
    pres = tmp_path / "03_reconstruction" / "presentation"
    pres.mkdir(parents=True)
    (pres / "forward_times.json").write_text(
        json.dumps(
            {
                "n_ok": 1,
                "n_converged": 1,
                "n_times": 1,
                "window_currents": "inverse_dump_currents",
                "per_time": [{"status": "converged"}],
            }
        ),
        encoding="utf-8",
    )
    fwd = forward_gate_summary(tmp_path)
    assert fwd["demo_mode"] is True
    assert fwd["science_role"] == "shape_demo_frozen_dump_currents"
    assert "demo" in str(fwd.get("publish_as", "")).lower()


def test_evolutive_science_kpis_and_passives_ab_blocked(tmp_path: Path) -> None:
    evo = tmp_path / "03_reconstruction" / "evolutive"
    evo.mkdir(parents=True)
    (tmp_path / "inputs").mkdir()
    pd.DataFrame(
        {
            "t_abs": [0.2, 0.21],
            "Ip": [1.0e6, 1.0e6],
            "Raxis": [0.9, 1.0],
            "Zaxis": [0.0, 0.0],
            "step_ok": [True, True],
        }
    ).to_csv(evo / "history.csv", index=False)
    pd.DataFrame({"time": [0.2, 0.21], "ip": [1.0e6, 1.0e6]}).to_csv(
        tmp_path / "inputs" / "ip.csv", index=False
    )
    (evo / "evolutive_meta.json").write_text(
        json.dumps(
            {
                "clamp_ip_to_measured": True,
                "n_passive": 0,
                "early_stop": "axis_drift",
                "abort_when_axis_drift_m": 0.12,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "inputs" / "passive_resistivity.json").write_text(
        json.dumps({"status": "awaiting_authority", "components": {}}),
        encoding="utf-8",
    )
    kpis = evolutive_science_kpis(tmp_path)
    assert kpis["ip_status"] == "clamp_tautology"
    assert kpis["n_passive"] == 0
    assert kpis["primary_metric"] == "raxis_drift"
    assert kpis["science_grade_ready"] is False
    ab = passives_ab_readiness(tmp_path)
    assert ab["blocked"] is True
    audit = build_science_audit(tmp_path)
    assert audit["version"] == "1.7"
    assert audit["evolutive_science_kpis"]["early_stop"] == "axis_drift"
    overlay = write_shot_expert_overlay(
        tmp_path, shot=30201, manifest={"status": "ok"}, science_audit=audit
    )
    md = (tmp_path / overlay["summary_md"]).read_text(encoding="utf-8")
    assert "What you may publish" in md
    assert "Evolutive science KPIs" in md


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
    assert audit["forward_gate"]["not_inverse_dn_peer"] is True
    assert "publish_claims" in audit
    assert "passives_ab" in audit

    man = {
        "status": "success",
        "blocking_errors": [],
        "stage_log": [],
        "time_window": {"t_start": 0.2, "t_end": 0.4},
    }
    (tmp_path / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    overlay = write_shot_expert_overlay(tmp_path, shot=30201, manifest=man, science_audit=audit)
    md = (tmp_path / overlay["summary_md"]).read_text(encoding="utf-8")
    assert "Science residuals" in md
    assert "Presentation annex" in md
    assert "from_current_ohmic" in md.lower() or "I×R" in md or "I*R" in md or "ohmic" in md.lower()
    assert "What you may publish" in md


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
