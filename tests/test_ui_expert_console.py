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
    assert panels.efit_panel(30203, run) is not None
    assert panels.shot_dossier(30203, run) is not None
    assert panels.downloads_table(30203, run, query="summary") is not None


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
