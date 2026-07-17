"""Window inference/QC/consensus must read the files extract actually writes.

Extract emits ip.csv and magnetics_timeseries.csv (not the legacy
magnetics_raw.csv), so windowing must prefer the dedicated Ip export and QC
must not fall over with qc_source_read_error on real run folders.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

from mast_freegsnke.window_consensus import infer_consensus_window
from mast_freegsnke.window_quality import evaluate_time_window
from mast_freegsnke.windowing import infer_time_window


def _write_extract_outputs(d: Path) -> None:
    t = [i * 0.01 for i in range(100)]
    ip = [0.0] * 20 + [1.0e6] * 60 + [0.0] * 20
    pd.DataFrame({"time": t, "ip": ip}).to_csv(d / "ip.csv", index=False)
    pd.DataFrame({"time": t, "flux_loop_01": ip}).to_csv(
        d / "magnetics_timeseries.csv", index=False
    )
    pd.DataFrame({"time": t, "SOL": ip}).to_csv(d / "pf_active_raw.csv", index=False)


def test_windowing_prefers_ip_csv(tmp_path: Path) -> None:
    _write_extract_outputs(tmp_path)
    tw = infer_time_window(inputs_dir=tmp_path, formed_frac=0.8)
    assert tw.source == "ip.csv"
    assert tw.signal_column == "ip"
    assert tw.t_start == pytest.approx(0.20)
    assert tw.t_end == pytest.approx(0.79)


def test_consensus_uses_extract_outputs(tmp_path: Path) -> None:
    _write_extract_outputs(tmp_path)
    cw = infer_consensus_window(inputs_dir=tmp_path, formed_frac=0.8)
    assert "ip.csv" in cw.sources_used
    # PF proxy windows are audited but do not vote when Ip sources exist.
    assert "pf_active_raw.csv" in cw.per_source
    assert "pf_active_raw.csv" not in cw.sources_used


def test_consensus_ip_sources_beat_pf_proxies(tmp_path: Path) -> None:
    """PF currents flow before plasma forms; they must not drag the
    consensus window into pre-plasma time when an Ip source exists."""
    t = [i * 0.01 for i in range(100)]
    # Ip: formed plasma between 0.20 and 0.79 s.
    ip = [0.0] * 20 + [1.0e6] * 60 + [0.0] * 20
    # PF: strong current early (pre-plasma), typical solenoid ramp.
    pf = [1.0e4] * 10 + [0.0] * 90
    pd.DataFrame({"time": t, "ip": ip}).to_csv(tmp_path / "ip.csv", index=False)
    pd.DataFrame({"time": t, "SOL": pf}).to_csv(tmp_path / "pf_active_raw.csv", index=False)

    cw = infer_consensus_window(inputs_dir=tmp_path, formed_frac=0.8)
    assert cw.t_start >= 0.19, f"consensus dragged pre-plasma: {cw.t_start}..{cw.t_end}"
    assert cw.sources_used == ["ip.csv"]
    assert any(n.startswith("proxy_sources_excluded_ip_available") for n in cw.notes)


def test_consensus_falls_back_to_proxies_without_ip(tmp_path: Path) -> None:
    t = [i * 0.01 for i in range(100)]
    pf = [0.0] * 30 + [1.0e4] * 40 + [0.0] * 30
    pd.DataFrame({"time": t, "SOL": pf}).to_csv(tmp_path / "pf_active_raw.csv", index=False)

    cw = infer_consensus_window(inputs_dir=tmp_path, formed_frac=0.8)
    assert cw.sources_used == ["pf_active_raw.csv"]
    assert "no_ip_source_available_proxy_consensus" in cw.notes


def test_window_qc_reads_extract_outputs(tmp_path: Path) -> None:
    _write_extract_outputs(tmp_path)
    tw = infer_time_window(inputs_dir=tmp_path, formed_frac=0.8)
    diag = evaluate_time_window(inputs_dir=tmp_path, tw=tw)
    assert not any(f.startswith("qc_source_read_error") for f in diag.flags)
    assert diag.max_abs == pytest.approx(1.0e6)


def test_window_qc_consensus_source_falls_back_to_existing_file(tmp_path: Path) -> None:
    """QC on a consensus-labelled window must pick a real input file."""
    from mast_freegsnke.windowing import TimeWindow

    _write_extract_outputs(tmp_path)
    tw = TimeWindow(
        t_start=0.20,
        t_end=0.79,
        source="consensus:endpoint_grid_max_coverage",
        signal_column=None,
        threshold=None,
    )
    diag = evaluate_time_window(inputs_dir=tmp_path, tw=tw)
    assert not any(f.startswith("qc_source_read_error") for f in diag.flags)
