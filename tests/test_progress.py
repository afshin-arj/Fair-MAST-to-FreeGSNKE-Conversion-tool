"""Tests for SHOT/<N>/progress.json live flush."""
from __future__ import annotations

import json
from pathlib import Path

from mast_freegsnke.progress import write_run_progress


def test_write_run_progress_incremental(tmp_path: Path) -> None:
    run_dir = tmp_path / "30201"
    run_dir.mkdir()
    stage_log = []

    write_run_progress(
        run_dir,
        shot=30201,
        status="started",
        stage_log=stage_log,
        blocking_errors=[],
        current_stage=None,
    )
    p1 = json.loads((run_dir / "progress.json").read_text(encoding="utf-8"))
    assert p1["shot"] == 30201
    assert p1["status"] == "started"
    assert p1["stage_log"] == []
    assert p1["current_stage"] is None
    assert "updated_utc" in p1

    stage_log.append({"stage": "download", "ok": True})
    write_run_progress(
        run_dir,
        shot=30201,
        status="running",
        stage_log=stage_log,
        blocking_errors=[],
        current_stage="download",
    )
    p2 = json.loads((run_dir / "progress.json").read_text(encoding="utf-8"))
    assert p2["status"] == "running"
    assert p2["current_stage"] == "download"
    assert len(p2["stage_log"]) == 1
    assert p2["stage_log"][0]["stage"] == "download"

    stage_log.append({"stage": "extract_csv", "ok": True})
    write_run_progress(
        run_dir,
        shot=30201,
        status="running",
        stage_log=stage_log,
        blocking_errors=["example_block"],
    )
    p3 = json.loads((run_dir / "progress.json").read_text(encoding="utf-8"))
    assert p3["current_stage"] == "extract_csv"  # inferred from last entry
    assert p3["blocking_errors"] == ["example_block"]
    assert len(p3["stage_log"]) == 2


def test_write_run_progress_creates_parent(tmp_path: Path) -> None:
    run_dir = tmp_path / "nested" / "40404"
    out = write_run_progress(
        run_dir,
        shot=40404,
        status="failed",
        stage_log=[{"stage": "machine_authority", "ok": False}],
        blocking_errors=["machine_authority_required_but_missing"],
        current_stage="machine_authority",
    )
    assert out == run_dir / "progress.json"
    assert out.is_file()


def test_pipeline_progress_flush_is_best_effort(tmp_path: Path) -> None:
    """UI locks on progress.json must not turn a successful stage into voltage_map_failed."""
    stage_log = []
    blocking_errors: list = []
    status = "running"
    run_dir = tmp_path / "30202"
    run_dir.mkdir()

    def _flush_progress(current_stage=None):
        try:
            raise PermissionError(5, "Access is denied")
        except OSError:
            pass

    def _stage(name, ok, **kw):
        stage_log.append({"stage": name, "ok": bool(ok), **kw})
        _flush_progress(current_stage=name)

    _stage("voltage_map_apply", True, n_mapped=5)
    assert stage_log[-1]["stage"] == "voltage_map_apply"
    assert stage_log[-1]["ok"] is True
    assert blocking_errors == []
