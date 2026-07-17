"""Rerunning a shot must not mix stale artifacts with fresh outputs.

A prior run (identified by manifest.json) is archived into history/<ts>/
before the new run writes anything. Prior runs are preserved, never deleted.
"""
from __future__ import annotations

import json
from pathlib import Path

from mast_freegsnke.pipeline import _archive_prior_run


def _make_prior_run(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(json.dumps({"status": "failed"}))
    (run_dir / "EXCEPTION_TRACEBACK.txt").write_text("boom")
    (run_dir / "inputs").mkdir()
    (run_dir / "inputs" / "ip.csv").write_text("time,ip\n0,0\n")
    (run_dir / "logs").mkdir()
    (run_dir / "logs" / "inverse.stdout.txt").write_text("old log")


def test_archive_prior_run_moves_everything(tmp_path: Path) -> None:
    run_dir = tmp_path / "30201"
    _make_prior_run(run_dir)

    dest = _archive_prior_run(run_dir)
    assert dest is not None and dest.startswith("history")

    # Top level is clean except history/.
    remaining = [p.name for p in run_dir.iterdir()]
    assert remaining == ["history"]

    # Everything preserved under history/<ts>/.
    hist = run_dir / dest
    assert (hist / "manifest.json").exists()
    assert (hist / "EXCEPTION_TRACEBACK.txt").exists()
    assert (hist / "inputs" / "ip.csv").exists()
    assert (hist / "logs" / "inverse.stdout.txt").exists()


def test_archive_prior_run_noop_on_fresh_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "30201"
    run_dir.mkdir()
    assert _archive_prior_run(run_dir) is None
    assert list(run_dir.iterdir()) == []


def test_archive_prior_run_stacks_multiple_reruns(tmp_path: Path) -> None:
    run_dir = tmp_path / "30201"
    _make_prior_run(run_dir)
    first = _archive_prior_run(run_dir)

    # Simulate a second completed run, then a third rerun.
    (run_dir / "manifest.json").write_text(json.dumps({"status": "success"}))
    second = _archive_prior_run(run_dir)

    assert first is not None and second is not None
    assert first != second
    assert (run_dir / first / "EXCEPTION_TRACEBACK.txt").exists()
    assert (run_dir / second / "manifest.json").exists()
