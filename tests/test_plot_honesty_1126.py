"""v11.26.0 — aspect helper + Evolutive plot honesty + presentation advisories."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from mast_freegsnke.equilibrium_presentation import apply_equal_aspect_rz
from mast_freegsnke.science_audit import presentation_advisories
from mast_freegsnke.shot_summary import write_shot_expert_overlay

REPO = Path(__file__).resolve().parents[1]


def test_apply_equal_aspect_rz_sets_limits_then_box() -> None:
    ax = MagicMock()
    apply_equal_aspect_rz(ax, xlim=(0.2, 1.8), ylim=(-1.5, 1.5))
    ax.set_xlim.assert_called_once_with(0.2, 1.8)
    ax.set_ylim.assert_called_once_with(-1.5, 1.5)
    ax.set_aspect.assert_called_once_with("equal", adjustable="box")


def test_efit_side_by_side_uses_box_aspect() -> None:
    src = (REPO / "src" / "mast_freegsnke" / "efit_side_by_side.py").read_text(
        encoding="utf-8"
    )
    assert "apply_equal_aspect_rz" in src
    assert 'adjustable="datalim"' not in src
    assert "adjustable='datalim'" not in src


def test_evolutive_template_plot_honesty() -> None:
    tpl = (REPO / "templates" / "evolutive_run.py.tpl").read_text(encoding="utf-8")
    assert "use_inverse_dump_lcfs=False" in tpl
    assert "use_inverse_targets=False" in tpl
    assert "LCFS (Evolutive)" in tpl
    assert "lcfs_arrays_from_eq" in tpl
    assert 'plot_style", "curated"' in tpl or "plot_style', 'curated'" in tpl
    assert 'plot_style", "freegsnke_native"' not in tpl
    assert "early_stop=axis_drift" in tpl
    assert "not an Ip-collapse claim" in tpl
    # Must not blame Ip for every early_stop
    assert "Ip diverged from measured" not in tpl


def test_forward_template_not_inverse_dn_banner() -> None:
    tpl = (REPO / "templates" / "forward_run.py.tpl").read_text(encoding="utf-8")
    assert "not Inverse DN" in tpl


def test_presentation_advisories_shape_unverified_and_lcfs(tmp_path: Path) -> None:
    run = tmp_path / "SHOT" / "30201"
    (run / "04_efit_compare").mkdir(parents=True)
    (run / "inverse_result.json").write_text(
        json.dumps(
            {
                "status": "gs_converged_shape_unverified",
                "shape_audit": {"shape_status": "gs_converged_shape_unverified"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "04_efit_compare" / "shape_scorecard.json").write_text(
        json.dumps(
            {
                "lcfs_distance": {"mean_nn_symmetric_m": 0.26},
                "rows": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "evolutive").mkdir()
    (run / "evolutive" / "evolutive_meta.json").write_text(
        json.dumps({"early_stop": "axis_drift"}) + "\n", encoding="utf-8"
    )
    adv = presentation_advisories(run)
    assert adv["available"] is True
    assert adv["high_lcfs_residual"] is True
    blob = " ".join(adv["items"])
    assert "shape_unverified" in blob
    assert "0.260" in blob or "0.26" in blob
    assert "axis_drift" in blob


def test_summary_includes_presentation_advisories(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    (run / "01_summary").mkdir(parents=True)
    (run / "inputs").mkdir()
    (run / "inputs" / "window.json").write_text(
        json.dumps({"t_start": 0.2, "t_end": 0.4}) + "\n", encoding="utf-8"
    )
    manifest = {"shot": 30201, "status": "ok", "stage_log": []}
    (run / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    science_audit = {
        "inverse_shape_gate": {
            "available": True,
            "n_gs_ok_shape_unverified": 1,
            "t0": {"status": "gs_converged_shape_unverified"},
        },
        "forward_gate": {"available": False},
        "presentation_advisories": {
            "available": True,
            "items": ["Test advisory: Forward ≠ Inverse DN"],
        },
        "evolutive_ip": {},
        "ohmic_drive": {},
        "phase_timeline": {},
        "passive_resistivity": {},
        "reconstruction_quality": {},
    }
    (run / "01_summary" / "science_audit.json").write_text(
        json.dumps(science_audit) + "\n", encoding="utf-8"
    )
    write_shot_expert_overlay(run, shot=30201, manifest=manifest, science_audit=science_audit)
    md = (run / "01_summary" / "SUMMARY.md").read_text(encoding="utf-8")
    assert "## Presentation advisories" in md
    assert "Test advisory: Forward ≠ Inverse DN" in md
