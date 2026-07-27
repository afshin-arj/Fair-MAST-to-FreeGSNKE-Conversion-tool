"""Inverse failure must not cascade into forward FileNotFound + 90 contract errors."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_pipeline_gates_forward_and_contracts_on_inverse() -> None:
    src = (REPO / "src" / "mast_freegsnke" / "pipeline.py").read_text(encoding="utf-8")
    assert "skipped_inverse_not_ok" in src
    assert 'mode == "both" and not inv_ok' in src
    assert 'note="skipped_inverse_not_ok"' in src


def test_inverse_template_t0_uses_hard_kill_not_uncapped_solve() -> None:
    tpl = (REPO / "templates" / "inverse_run.py.tpl").read_text(encoding="utf-8")
    main = tpl.split("def main(", 1)[1]
    # t0 path must call hard-kill helper before dump / multitime synthetics.
    assert "[..] t0" in main
    assert "restore_optimized_currents" in main
    assert "_solve_one_sample(" in main
    assert "t0_solve_mode" in main
    # Must not keep the old uncapped t0 solver.solve without max_solving_iterations.
    # (Multitime child still uses solver.solve inside _solve_one_sample_inplace.)
    before_synth = main.split("write_synthetic_probe_csvs", 1)[0]
    # Direct t0 solve in main must go through _solve_one_sample (hard kill).
    assert before_synth.count("_solve_one_sample(") >= 1
