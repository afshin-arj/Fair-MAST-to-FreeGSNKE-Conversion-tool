"""Expert console UI kit + authority matrix smoke tests."""
from __future__ import annotations

import json
from pathlib import Path

from mast_freegsnke_ui import artifacts as art
from mast_freegsnke_ui import panels
from mast_freegsnke_ui import ui_kit


def test_ui_kit_status_and_fmt() -> None:
    assert ui_kit.status_tone("success") == "ok"
    assert ui_kit.status_tone("failed") == "fail"
    assert ui_kit.status_tone("awaiting_authority") == "warn"
    assert ui_kit.fmt_kpi(None) == "—"
    assert ui_kit.fmt_kpi(True) == "yes"
    assert ui_kit.fmt_delta(12.0).startswith("+")
    assert ui_kit.fmt_delta(-1.0).startswith("−")


def test_authority_matrix_includes_awaiting_calibration(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"shot": 30201, "blocking_errors": []}) + "\n")
    snap = art.authority_snapshot(run)
    assert "matrix" in snap
    by = {r["label"]: r for r in snap["matrix"]}
    assert "diagnostic_calibration" in by
    assert by["diagnostic_calibration"]["status"] in {"awaiting", "missing"}
    assert by["coil_map.resolved"]["present"] is False


def test_overview_and_auth_panels_smoke(tmp_path: Path) -> None:
    run = tmp_path / "30203"
    run.mkdir()
    (run / "01_summary").mkdir()
    (run / "01_summary" / "SUMMARY.json").write_text(
        json.dumps(
            {
                "shot": 30203,
                "status": "success",
                "window": {"t_start": 0.1, "t_end": 0.3},
                "modes": {"inverse": "ok"},
                "blocking_errors": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "manifest.json").write_text(
        json.dumps({"shot": 30203, "status": "success", "blocking_errors": []}) + "\n",
        encoding="utf-8",
    )
    assert panels.overview_panel(30203, run) is not None
    assert panels.auth_panel(30203, run) is not None
    assert panels.residuals_panel(30203, run) is not None
    assert panels.planner_panel(30203, run) is not None
    assert panels.efit_panel(30203, run) is not None
    assert panels.shot_dossier(30203, run) is not None
    assert panels.downloads_table(30203, run, query="summary") is not None
    assert ("planner", "Planner") in panels.TAB_DEFS
    assert panels.fill_one_tab("planner", 30203, run) is not None


def test_planner_panel_with_products(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    run.mkdir()
    (run / "07_planner").mkdir()
    (run / "07_planner" / "PLANNER.json").write_text(
        json.dumps(
            {
                "method": "gspulse_python",
                "method_version": "v1.3",
                "picard": True,
                "picard_mode": "forward_gs_freeze_plasma_offsets",
                "picard_status": "ok",
                "isoflux_cost": True,
                "isoflux_mode": "vacuum_coil_greens_plus_plasma_picard",
                "isoflux_status": "ok",
                "psi_bry_cost": True,
                "psi_bry_mode": "archive_boundary_flux",
                "psi_bry_status": "ok",
                "isoflux_residuals": {
                    "used": True,
                    "planned": {
                        "isoflux_rms_mean": 0.01,
                        "xpoint_B_rms_mean": 0.02,
                        "psi_bry_rms_mean": 0.03,
                    },
                },
                "status": "ok",
                "n_knots": 21,
                "residual_rms_mean_V": 1.2,
                "residual_rms_mean_measured_V": 0.8,
                "n_voltage_violations_raw": 0,
                "circuit_dynamics_mutuals": "freegsnke_offdiag_retained_cited_Lii_overlay",
                "limitations": ["passives awaiting resistivity authority"],
                "shape_targets_available": {
                    "present": True,
                    "status": "ok",
                    "found_scalars": ["wmhd", "x_point_r"],
                    "n_knots_with_lcfs_control_points": 5,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "07_planner" / "planning_residual_vs_measured_V.csv").write_text(
        "circuit,drive_label,rms_V,mae_V,max_abs_V,n\n"
        "Solenoid,measured_fairmast_V,1.0,0.5,2.0,21\n",
        encoding="utf-8",
    )
    (run / "07_planner" / "planning_voltage_residual.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (run / "07_planner" / "planning_current_residual.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (run / "07_planner" / "picard.json").write_text(
        json.dumps({"history": [{"outer": 1, "n_gs_ok": 21, "n_gs_fail": 0}], "note": "ok"})
        + "\n",
        encoding="utf-8",
    )
    (run / "07_planner" / "plasma_scalars.json").write_text(
        json.dumps(
            {
                "inventory": {"ip_present": True, "profile_trajectory_status": "ok"},
                "psi_bry": {"used": True, "mode": "archive_boundary_flux", "status": "ok"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "07_planner" / "shape_targets.json").write_text(
        json.dumps({"present": True, "status": "ok", "found_scalars": ["wmhd"]}) + "\n",
        encoding="utf-8",
    )
    (run / "inputs" / "planner_authority").mkdir(parents=True)
    (run / "inputs" / "planner_authority" / "planner_authority.json").write_text(
        json.dumps({"authority_name": "planner", "enabled": True}) + "\n",
        encoding="utf-8",
    )
    info = art.load_planner_info(run)
    assert info["method"] == "gspulse_python"
    assert info["method_version"] == "v1.3"
    assert info["picard"] is True
    assert info["picard_mode"] == "forward_gs_freeze_plasma_offsets"
    assert info["isoflux_cost"] is True
    assert info["isoflux_mode"] == "vacuum_coil_greens_plus_plasma_picard"
    assert info["isoflux_rms_mean"] == 0.01
    assert info["psi_bry_rms_mean"] == 0.03
    assert info["shape_targets_present"] is True
    assert info["plot_i_rel"] is not None
    assert info["plot_rel"] is not None
    assert info["authority_hashes"].get("planner_authority")
    assert len(info["residual_rows"]) == 1
    assert len(info["picard_history"]) == 1
    panel = panels.planner_panel(30201, run)
    assert panel is not None
    text = str(panel)
    assert "Authority hashes" in text or "honesty" in text.lower() or "Feedforward" in text
    assert panels.fill_one_tab("planner", 30201, run) is not None
    assert "B6-full" in panels.TAB_META["planner"] or "I/V" in panels.TAB_META["planner"]


def test_enrich_library_options(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    run.mkdir()
    (run / "01_summary").mkdir()
    (run / "01_summary" / "SUMMARY.json").write_text(
        json.dumps({"shot": 30201, "status": "failed", "blocking_errors": ["x"]}) + "\n"
    )
    (run / "manifest.json").write_text(
        json.dumps({"shot": 30201, "status": "failed", "blocking_errors": ["x"]}) + "\n"
    )
    opts = ui_kit.enrich_library_options(
        tmp_path,
        [{"label": "30201", "value": 30201}],
        overview_kpis_fn=art.overview_kpis,
        run_dir_for_fn=art.run_dir_for,
    )
    assert "failed" in opts[0]["label"]
