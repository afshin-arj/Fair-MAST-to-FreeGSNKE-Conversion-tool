"""Formed-plasma t0 estimate + FreeGSNKE isoflux packing checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from mast_freegsnke.formed_plasma import (
    estimate_formed_plasma_t_or_none,
    estimate_formed_plasma_time,
)


def test_estimate_formed_plasma_time_min_dipdt(tmp_path: Path) -> None:
    # Flat-top around t=0.22 with rising flanks → pick near flat region.
    rows = ["time,ip\n"]
    for i in range(41):
        t = 0.18 + i * 0.002
        if t < 0.20:
            ip = 5e5 + (t - 0.18) / 0.02 * 3e5
        elif t > 0.26:
            ip = 8e5 - (t - 0.26) / 0.02 * 2e5
        else:
            ip = 8e5
        rows.append(f"{t},{ip}\n")
    p = tmp_path / "ip.csv"
    p.write_text("".join(rows), encoding="utf-8")
    t, ip, ip_max = estimate_formed_plasma_time(p, frac=0.8)
    assert ip_max == pytest.approx(8e5)
    assert 0.20 <= t <= 0.26
    assert ip == pytest.approx(8e5)
    assert estimate_formed_plasma_t_or_none(tmp_path / "missing.csv") is None


def test_freegsnke_dn_isoflux_packing_accepted() -> None:
    """DN nulls (2,3) + isoflux [[R],[Z]] → Inverse_optimizer (2,N) sets."""
    pytest.importorskip("freegsnke")
    import numpy as np
    from freegsnke.inverse import Inverse_optimizer

    null_points = [
        [0.55, 0.92, 0.62],
        [-1.17, 0.03, 1.19],
    ]
    r = [0.55 + 0.02 * i for i in range(10)]
    z = [-1.0 + 0.2 * i for i in range(10)]
    isoflux_set = [[r, z]]
    for payload in (isoflux_set, np.array(isoflux_set, dtype=float)):
        opt = Inverse_optimizer(null_points=null_points, isoflux_set=payload)
        assert np.asarray(opt.null_points).shape == (2, 3)
        assert len(opt.isoflux_set) == 1
        assert np.asarray(opt.isoflux_set[0]).shape == (2, 10)
        assert opt.isoflux_set_n == [10]
