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


def test_inverse_template_normalises_profiles_before_pprime_dump() -> None:
    """After hard-kill restore, fresh ConstrainPaxisIp lacks L/Beta0 until Jtor.

    Without Jtor + guarded pprime, t0 forward_gs fallback aborts before
    inverse_dump.pkl (shot 30202 regression under 11.19.2).
    """
    tpl = (REPO / "templates" / "inverse_run.py.tpl").read_text(encoding="utf-8")
    dump_region = tpl.split("import pickle", 1)[1].split("with open(HERE/\"inverse_dump.pkl\"", 1)[0]
    assert "profiles.Jtor(" in dump_region
    assert "pprime/ffprime dump skipped" in dump_region
    assert "pprime=_pprime" in dump_region
    assert "eq._profiles = profiles" in dump_region


def test_inverse_template_plot_failsoft_after_dump() -> None:
    """Plot / optional TORAX must not abort after inverse_dump.pkl is written."""
    tpl = (REPO / "templates" / "inverse_run.py.tpl").read_text(encoding="utf-8")
    after_dump = tpl.split('print("Saved inverse_dump.pkl")', 1)[1]
    assert "never abort after a successful dump" in after_dump or "inverse_equilibrium.png failed" in after_dump
    assert "eq.plot failed" in after_dump
    # Optional TORAX must warn, not re-raise.
    torax = after_dump.split("ADR-001", 1)[1].split("write_synthetic_probe_csvs", 1)[0]
    assert "raise" not in torax
    assert "torax geometry export failed" in torax
