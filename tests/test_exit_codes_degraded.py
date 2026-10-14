"""Exit-code semantics: success (0) vs degraded (17) vs failed (11).

Regression tests for the audit fix that made a *degraded* run distinguishable
from a *failed* run at the process exit-code level, in both the single-shot
CLI path (``run_exit_for_manifest``) and the shared batch loop
(``run_shot_batch``): degraded must be surfaced (non-zero) without being
treated as a failure (no abort-on-failure, ranked below hard failures).
"""

from __future__ import annotations

from pathlib import Path

from mast_freegsnke.batch import run_shot_batch
from mast_freegsnke.exit_codes import EXIT_DEGRADED, EXIT_FAILED, run_exit_for_manifest


def test_manifest_success_is_zero() -> None:
    assert run_exit_for_manifest({"status": "success", "blocking_errors": []}) == 0


def test_manifest_degraded_maps_to_17() -> None:
    rc = run_exit_for_manifest(
        {"status": "degraded", "blocking_errors": [], "degraded_notes": ["evolutive_soft_timeout:..."]}
    )
    assert rc == EXIT_DEGRADED == 17


def test_manifest_failed_maps_to_11() -> None:
    assert run_exit_for_manifest({"status": "failed", "blocking_errors": ["coil_map_invalid"]}) == EXIT_FAILED


def test_blockers_override_success_or_degraded_status() -> None:
    assert run_exit_for_manifest({"status": "success", "blocking_errors": ["x"]}) == EXIT_FAILED
    assert run_exit_for_manifest({"status": "degraded", "blocking_errors": ["x"]}) == EXIT_FAILED


def test_missing_or_unknown_status_fails_closed() -> None:
    assert run_exit_for_manifest({}) == EXIT_FAILED
    assert run_exit_for_manifest(None) == EXIT_FAILED
    assert run_exit_for_manifest({"status": "weird"}) == EXIT_FAILED


def test_batch_degraded_is_not_a_failure(tmp_path: Path, capsys) -> None:
    codes = {1: 0, 2: EXIT_DEGRADED}

    def run_one(shot: int) -> int:
        return codes[shot]

    # abort_on_failure must NOT trigger on a degraded run.
    rc = run_shot_batch([1, 2], run_one, runs_dir=tmp_path, abort_on_failure=True)
    out = capsys.readouterr().out
    assert rc == EXIT_DEGRADED
    assert "[DEGRADED]" in out
    assert "[FAIL]" not in out
    assert "batch_abort_on_failure" not in out


def test_batch_hard_failure_outranks_degraded(tmp_path: Path) -> None:
    codes = {1: EXIT_DEGRADED, 2: EXIT_FAILED}
    rc = run_shot_batch([1, 2], lambda s: codes[s], runs_dir=tmp_path, abort_on_failure=False)
    # 11 must win over 17 despite being numerically smaller.
    assert rc == EXIT_FAILED


def test_batch_all_success_is_zero(tmp_path: Path) -> None:
    assert run_shot_batch([1, 2], lambda s: 0, runs_dir=tmp_path) == 0


def test_batch_degraded_summary_marks_degraded(tmp_path: Path, capsys) -> None:
    rc = run_shot_batch([7], lambda s: EXIT_DEGRADED, runs_dir=tmp_path)
    out = capsys.readouterr().out
    assert rc == EXIT_DEGRADED
    # Single-shot batches stay quiet (summary only for multi-shot/unsuitable),
    # but the per-shot line still reports DEGRADED, not FAIL.
    assert "[DEGRADED] Shot 7" in out
    assert "[FAIL]" not in out
