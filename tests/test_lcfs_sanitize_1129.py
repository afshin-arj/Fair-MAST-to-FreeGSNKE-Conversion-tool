"""LCFS domain sanitization — no R<0 / R<Rmin beaks through the solenoid."""

from __future__ import annotations

import numpy as np

from mast_freegsnke.freegsnke_lcfs import (
    grid_bounds_from_eq,
    lcfs_arrays_from_eq,
    sanitize_lcfs_polyline,
)


def test_sanitize_drops_negative_r_and_keeps_longest_run() -> None:
    # Closed-ish loop with a domain-exterior beak (R≈−0.1) then valid arc.
    theta = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    r = 0.8 + 0.3 * np.cos(theta)
    z = 0.4 * np.sin(theta)
    # Inject unphysical CS-crossing samples in the middle
    r = np.concatenate([r[:10], np.array([-0.10, -0.05, 0.05]), r[10:]])
    z = np.concatenate([z[:10], np.array([0.0, 0.1, -0.1]), z[10:]])
    out = sanitize_lcfs_polyline(r, z, r_min=0.1, r_max=2.0, z_min=-2.0, z_max=2.0)
    assert out is not None
    rr, zz = out
    assert float(np.min(rr)) >= 0.1
    assert len(rr) >= 3
    assert len(rr) == len(zz)


def test_sanitize_rejects_all_exterior() -> None:
    assert sanitize_lcfs_polyline([-0.1, -0.05, 0.0], [0.0, 0.1, -0.1], r_min=0.1) is None


def test_lcfs_arrays_from_eq_sanitizes_separatrix() -> None:
    class _Eq:
        Rmin = 0.1
        Rmax = 2.0
        Zmin = -2.0
        Zmax = 2.0
        R = np.linspace(0.1, 2.0, 8)
        Z = np.linspace(-2.0, 2.0, 8)

        def separatrix(self, ntheta=201):
            th = np.linspace(0, 2 * np.pi, int(ntheta), endpoint=False)
            rr = 0.9 + 0.4 * np.cos(th)
            zz = 0.5 * np.sin(th)
            # Classic FreeGSNKE artifact: a few R≈−0.1 samples
            rr[0] = -0.1005
            rr[1] = -0.08
            return np.vstack([rr, zz])

    got = lcfs_arrays_from_eq(_Eq())
    assert got is not None
    rr, _zz = got
    assert float(np.min(rr)) >= 0.1


def test_grid_bounds_from_eq() -> None:
    class _Eq:
        Rmin = 0.1
        Rmax = 1.8
        Zmin = -1.5
        Zmax = 1.5

    b = grid_bounds_from_eq(_Eq())
    assert b["Rmin"] == 0.1
    assert b["Rmax"] == 1.8


def test_forward_template_still_honest() -> None:
    from pathlib import Path

    tpl = (Path(__file__).resolve().parents[1] / "templates" / "forward_run.py.tpl").read_text(
        encoding="utf-8"
    )
    assert "use_inverse_dump_lcfs=False" in tpl
    assert "lcfs_arrays_from_eq" in tpl
