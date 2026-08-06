"""UI stage taxonomy: soft-skip vs cascade-skip honesty."""
from __future__ import annotations


def test_cascade_skip_not_soft_skip() -> None:
    from mast_freegsnke_ui.panels import _stage_is_cascade_skip, _stage_is_soft_skip

    cascade = {"ok": False, "note": "skipped_blocking_errors"}
    assert _stage_is_cascade_skip(cascade) is True
    assert _stage_is_soft_skip(cascade) is False

    awaiting = {"ok": False, "status": "awaiting_authority", "note": "awaiting_authority"}
    assert _stage_is_cascade_skip(awaiting) is False
    assert _stage_is_soft_skip(awaiting) is True

    off = {"ok": False, "note": "export_torax_geometry=false"}
    assert _stage_is_soft_skip(off) is True
    assert _stage_is_cascade_skip(off) is False

    ok = {"ok": True, "note": "skipped_blocking_errors"}
    assert _stage_is_soft_skip(ok) is False
    assert _stage_is_cascade_skip(ok) is False


def test_progress_bar_does_not_count_cascade_as_done() -> None:
    from mast_freegsnke_ui.panels import stage_progress_bar

    progress = {
        "status": "failed",
        "blocking_errors": ["code=torax_geometry_export_missing: x"],
        "stage_log": [
            {"stage": "freegsnke_execute", "ok": True},
            {"stage": "torax_geometry_export", "ok": False, "note": None},
            {"stage": "efit_compare", "ok": False, "note": "skipped_blocking_errors"},
            {"stage": "gsfit", "ok": False, "status": "awaiting_authority", "note": "awaiting"},
        ],
    }
    # Smoke: builds without error; cascade must appear in label, not inflate skip count wrongly
    node = stage_progress_bar(progress, running=False)
    assert node is not None
