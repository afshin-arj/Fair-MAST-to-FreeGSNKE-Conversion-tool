"""Tests for ADR-001 optional TORAX GEQDSK export authority (no invented metrology)."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from mast_freegsnke.config import AppConfig
from mast_freegsnke.torax_geometry_export import (
    ToraxGeometryExportAuthority,
    ToraxGeometryExportError,
    _critical_points_empty,
    export_torax_geqdsk_from_equilibrium,
    load_torax_geometry_export_authority,
    write_geqdsk_declared_rcentr,
    write_torax_geometry_export_authority,
)


def _valid_auth(**over) -> ToraxGeometryExportAuthority:
    kw = dict(
        rcentr_m=0.85,
        rcentr_source="test citation",
        cocos_declared="freegs4e_geqdsk_native",
    )
    kw.update(over)
    return ToraxGeometryExportAuthority(**kw)


def test_authority_roundtrip(tmp_path: Path) -> None:
    auth = _valid_auth()
    path = write_torax_geometry_export_authority(tmp_path, auth)
    loaded = load_torax_geometry_export_authority(path)
    assert loaded.rcentr_m == pytest.approx(0.85)
    assert loaded.format == "geqdsk"
    assert loaded.forbid_chease is True


def test_authority_rejects_missing_rcentr() -> None:
    with pytest.raises(ToraxGeometryExportError, match="rcentr_m"):
        ToraxGeometryExportAuthority(
            rcentr_m=0.0,
            rcentr_source="x",
            cocos_declared="freegs4e_geqdsk_native",
        ).validate()


def test_authority_rejects_missing_cocos() -> None:
    with pytest.raises(ToraxGeometryExportError, match="cocos_declared"):
        ToraxGeometryExportAuthority(
            rcentr_m=0.85,
            rcentr_source="cite",
            cocos_declared="",
        ).validate()


def test_authority_rejects_chease() -> None:
    with pytest.raises(ToraxGeometryExportError, match="format"):
        ToraxGeometryExportAuthority(
            format="chease",
            rcentr_m=0.85,
            rcentr_source="cite",
            cocos_declared="x",
        ).validate()


def test_shipped_authority_validates() -> None:
    repo = Path(__file__).resolve().parents[1]
    auth = load_torax_geometry_export_authority(
        repo / "configs" / "torax_geometry_export_authority.json"
    )
    assert auth.rcentr_m > 0
    assert "ConstrainPaxisIp" in auth.profile_provenance


def test_default_config_export_off() -> None:
    repo = Path(__file__).resolve().parents[1]
    cfg = AppConfig.load(repo / "configs" / "default.json")
    assert cfg.export_torax_geometry is False
    assert cfg.torax_geometry_export_authority_path


def test_config_requires_path_when_export_on(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    base = json.loads(
        (Path(__file__).resolve().parents[1] / "configs" / "default.json").read_text(
            encoding="utf-8"
        )
    )
    base["export_torax_geometry"] = True
    base["torax_geometry_export_authority_path"] = None
    p.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="torax_geometry_export_authority_path"):
        AppConfig.load(p)


def test_inverse_template_mentions_torax_export() -> None:
    repo = Path(__file__).resolve().parents[1]
    tpl = (repo / "templates" / "inverse_run.py.tpl").read_text(encoding="utf-8")
    assert "export_torax_geqdsk_from_equilibrium" in tpl
    assert "try_load_torax_geometry_export_authority" in tpl
    assert "continuing after TORAX export failure" in tpl
    # Multitime shape gate must use ea["grid"] (NameError left soft-skips on 30201).
    assert 'grid=ea["grid"]' in tpl


def test_critical_points_empty_handles_numpy() -> None:
    assert _critical_points_empty(None) is True
    assert _critical_points_empty([]) is True
    assert _critical_points_empty(np.zeros((0, 3))) is True
    pts = np.array([[0.9, 0.0, 1.0], [0.85, 0.5, 0.5]], dtype=float)
    assert _critical_points_empty(pts) is False


def test_sign_ip_helper_never_returns_amps() -> None:
    from mast_freegsnke.torax_geometry_export import _sign_ip_from_eq

    class _EqPos:
        def plasmaCurrent(self):
            return 1.0e6

    class _EqNeg:
        def plasmaCurrent(self):
            return -8.5e5

    assert _sign_ip_from_eq(_EqPos()) == 1
    assert _sign_ip_from_eq(_EqNeg()) == -1


def test_write_geqdsk_psi_bndry_fallback_without_xpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When find_critical yields O but no X, use profiles.psi_bndry (SHOT/30201)."""
    import sys

    nx, ny = 8, 8
    R = np.linspace(0.2, 1.5, nx)
    Z = np.linspace(-1.2, 1.2, ny)
    RR, ZZ = np.meshgrid(R, Z, indexing="ij")
    psi = np.exp(-((RR - 0.9) ** 2 + ZZ**2) / 0.25)

    class _Prof:
        psi_bndry = 0.2
        opt = np.array([[0.9, 0.0, 1.0]], dtype=float)
        xpt = np.zeros((0, 3), dtype=float)

    class _Eq:
        R = RR
        Z = ZZ
        Rmin, Rmax = 0.2, 1.5
        Zmin, Zmax = -1.2, 1.2
        nx = 8
        ny = 8
        tokamak = SimpleNamespace(wall=None)
        _profiles = _Prof()

        def psi(self):
            return psi

        def fvac(self):
            return 0.5

        def plasmaCurrent(self):
            return -1.0e6  # wrong-sign amps must not be passed as signIp

        def fpol(self, p):
            return np.full_like(p, 0.5, dtype=float)

        def pressure(self, p):
            return np.zeros_like(p, dtype=float)

        def ffprime(self, p):
            return np.zeros_like(p, dtype=float)

        def pprime(self, p):
            return np.zeros_like(p, dtype=float)

        def q(self, p):
            return np.ones_like(p, dtype=float)

        def separatrix(self, ntheta=101):
            th = np.linspace(0, 2 * np.pi, int(ntheta), endpoint=False)
            return np.column_stack([0.9 + 0.3 * np.cos(th), 0.4 * np.sin(th)])

    op = np.array([[0.9, 0.0, 1.0]], dtype=float)
    xp_empty = np.zeros((0, 3), dtype=float)

    monkeypatch.setattr(
        "mast_freegsnke.torax_geometry_export._find_critical_points",
        lambda eq, psi_arr: (op, xp_empty, "test_no_x"),
    )

    def _fake_write(data, fh, label=None):
        fh.write(f"sibdry={data['sibdry']}\n")

    fake_geqdsk = SimpleNamespace(write=_fake_write)
    try:
        import freegs4e as _real_f4e

        monkeypatch.setattr(_real_f4e, "_geqdsk", fake_geqdsk)
    except ImportError:
        monkeypatch.setitem(sys.modules, "freegs4e", SimpleNamespace(_geqdsk=fake_geqdsk))
        monkeypatch.setitem(sys.modules, "freegs4e._geqdsk", fake_geqdsk)

    buf = io.StringIO()
    meta = write_geqdsk_declared_rcentr(_Eq(), buf, rcentr_m=0.85, label="test")
    assert meta["n_xpoint"] == 0
    assert "psi_bndry" in str(meta["critical_source"])
    assert "sibdry=-0.8" in buf.getvalue()  # 0.2 - 1.0


def test_write_geqdsk_accepts_numpy_critical_points(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: freegs4e find_critical returns ndarrays → old `if not opoint` crashed."""
    import sys

    nx, ny = 8, 8
    R = np.linspace(0.2, 1.5, nx)
    Z = np.linspace(-1.2, 1.2, ny)
    RR, ZZ = np.meshgrid(R, Z, indexing="ij")
    psi = np.exp(-((RR - 0.9) ** 2 + ZZ**2) / 0.25)

    class _Wall:
        R = np.array([0.2, 1.5, 1.5, 0.2])
        Z = np.array([-1.2, -1.2, 1.2, 1.2])

    class _Tok:
        wall = _Wall()

    class _Eq:
        R = RR
        Z = ZZ
        Rmin, Rmax = 0.2, 1.5
        Zmin, Zmax = -1.2, 1.2
        nx = 8
        ny = 8
        tokamak = _Tok()

        def psi(self):
            return psi

        def fvac(self):
            return 0.5

        def plasmaCurrent(self):
            return 1.0e6

        def fpol(self, p):
            return np.full_like(p, 0.5, dtype=float)

        def pressure(self, p):
            return np.zeros_like(p, dtype=float)

        def ffprime(self, p):
            return np.zeros_like(p, dtype=float)

        def pprime(self, p):
            return np.zeros_like(p, dtype=float)

        def q(self, p):
            return np.ones_like(p, dtype=float)

        def separatrix(self, ntheta=101):
            th = np.linspace(0, 2 * np.pi, int(ntheta), endpoint=False)
            return np.column_stack([0.9 + 0.3 * np.cos(th), 0.4 * np.sin(th)])

    op = np.array([[0.9, 0.0, 1.0]], dtype=float)
    xp = np.array([[0.85, 0.55, 0.2], [0.85, -0.55, 0.2]], dtype=float)

    monkeypatch.setattr(
        "mast_freegsnke.torax_geometry_export._find_critical_points",
        lambda eq, psi_arr: (op, xp, "test_numpy_critical"),
    )

    written = {"n": 0}

    def _fake_write(data, fh, label=None):
        written["n"] += 1
        fh.write(f"fake-geqdsk label={label} nx={data['nx']}\n")

    fake_geqdsk = SimpleNamespace(write=_fake_write)
    fake_freegs4e = SimpleNamespace(_geqdsk=fake_geqdsk, critical=SimpleNamespace())
    try:
        import freegs4e as _real_f4e

        monkeypatch.setattr(_real_f4e, "_geqdsk", fake_geqdsk)
    except ImportError:
        monkeypatch.setitem(sys.modules, "freegs4e", fake_freegs4e)
        monkeypatch.setitem(sys.modules, "freegs4e._geqdsk", fake_geqdsk)

    buf = io.StringIO()
    meta = write_geqdsk_declared_rcentr(_Eq(), buf, rcentr_m=0.85, label="test")
    assert written["n"] == 1
    assert meta["n_opoint"] == 1
    assert meta["n_xpoint"] == 2
    assert "fake-geqdsk" in buf.getvalue()


def test_export_atomic_no_empty_stub_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth = _valid_auth()
    out = tmp_path / auth.output_relpath

    def _boom(*_a, **_k):
        raise ToraxGeometryExportError("forced failure")

    monkeypatch.setattr(
        "mast_freegsnke.torax_geometry_export.write_geqdsk_declared_rcentr",
        _boom,
    )
    with pytest.raises(ToraxGeometryExportError, match="forced"):
        export_torax_geqdsk_from_equilibrium(tmp_path, object(), auth, shot=30201, t0=0.2)
    assert not out.exists()
    if out.parent.exists():
        assert not list(out.parent.glob("*.tmp"))
