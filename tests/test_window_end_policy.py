"""Window end policy: cut after/before Ip peak when |Ip| falls below declared floor."""

from pathlib import Path

import pandas as pd
import pytest

from mast_freegsnke.windowing import TimeWindow, apply_window_end_policy, infer_time_window


def _write_ip(tmp: Path, times, ip) -> None:
    pd.DataFrame({"time": times, "plasma_current": ip}).to_csv(tmp / "ip.csv", index=False)


def test_ip_peak_then_floor_cuts_rampdown(tmp_path: Path) -> None:
    # Peak at t=0.3 (120), then drops below 0.9*120=108 at t=0.5
    _write_ip(
        tmp_path,
        [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        [0.0, 50.0, 100.0, 120.0, 115.0, 100.0, 20.0],
    )
    base = TimeWindow(
        t_start=0.2,
        t_end=0.6,
        source="test",
        signal_column="plasma_current",
        threshold=96.0,
        note="formed",
    )
    out = apply_window_end_policy(
        base, tmp_path, policy="ip_peak_then_floor", end_ip_frac=0.90
    )
    assert out.t_start == 0.2
    assert out.t_end == 0.5
    assert "window_end_policy=ip_peak_then_floor" in (out.note or "")
    assert "cut=yes" in (out.note or "")
    assert "t_end_cut=" in (out.note or "")


def test_ip_prepeak_floor_excludes_late_spike(tmp_path: Path) -> None:
    # Flat-top ~100, then pre-disruption spike peak at t=0.5 (120).
    # floor = 0.9*120 = 108 → last pre-peak sample below floor is t=0.4.
    _write_ip(
        tmp_path,
        [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.55, 0.6],
        [0.0, 50.0, 100.0, 100.0, 100.0, 120.0, 115.0, 90.0],
    )
    base = TimeWindow(
        t_start=0.2,
        t_end=0.6,
        source="test",
        signal_column="plasma_current",
        threshold=96.0,
        note="formed",
    )
    pre = apply_window_end_policy(
        base, tmp_path, policy="ip_prepeak_floor", end_ip_frac=0.90
    )
    post = apply_window_end_policy(
        base, tmp_path, policy="ip_peak_then_floor", end_ip_frac=0.90
    )
    assert pre.t_end == 0.4
    assert "window_end_policy=ip_prepeak_floor" in (pre.note or "")
    assert "ip_peak_t=0.5" in (pre.note or "")
    assert "cut=yes" in (pre.note or "")
    # Post-peak still cuts after the spike (first |Ip|<108 after peak → 0.6)
    assert post.t_end == 0.6
    assert post.t_end > pre.t_end


def test_ip_peak_then_floor_keeps_end_when_no_cross(tmp_path: Path) -> None:
    _write_ip(
        tmp_path,
        [0.0, 0.1, 0.2, 0.3, 0.4],
        [0.0, 80.0, 100.0, 120.0, 119.0],
    )
    base = TimeWindow(
        t_start=0.2,
        t_end=0.4,
        source="test",
        signal_column="plasma_current",
        threshold=96.0,
        note="formed",
    )
    out = apply_window_end_policy(
        base, tmp_path, policy="ip_peak_then_floor", end_ip_frac=0.90
    )
    assert out.t_end == 0.4
    assert "cut=no" in (out.note or "")


def test_unknown_window_end_policy_fail_closed(tmp_path: Path) -> None:
    base = TimeWindow(
        t_start=0.1, t_end=0.9, source="x", signal_column=None, threshold=None
    )
    with pytest.raises(ValueError, match="Unknown window_end_policy"):
        apply_window_end_policy(base, tmp_path, policy="invented_policy", end_ip_frac=0.90)


def test_none_policy_passthrough(tmp_path: Path) -> None:
    base = TimeWindow(
        t_start=0.1, t_end=0.9, source="x", signal_column=None, threshold=None
    )
    out = apply_window_end_policy(base, tmp_path, policy="none", end_ip_frac=0.90)
    assert out.t_end == 0.9


def test_infer_then_floor_integration(tmp_path: Path) -> None:
    # Formed at 0.8*peak=96 → start 0.2 end 0.4 (threshold); floor cuts to 0.5?
    # Actually after peak 0.3, |Ip|<108 first at 0.5 — but threshold end is 0.4.
    # Floor cannot extend past threshold end → t_end stays 0.4.
    _write_ip(
        tmp_path,
        [0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
        [0.0, 0.0, 100.0, 120.0, 110.0, 50.0],
    )
    tw = infer_time_window(inputs_dir=tmp_path, formed_frac=0.8)
    assert tw.t_start == 0.2
    assert tw.t_end == 0.4
    refined = apply_window_end_policy(
        tw, tmp_path, policy="ip_peak_then_floor", end_ip_frac=0.90
    )
    # 110 at 0.4 is still >= 108, so no cut inside window → keep 0.4
    assert refined.t_end == 0.4
