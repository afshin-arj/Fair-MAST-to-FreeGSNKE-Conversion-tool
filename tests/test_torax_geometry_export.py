"""Tests for ADR-001 optional TORAX GEQDSK export authority (no invented metrology)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mast_freegsnke.config import AppConfig
from mast_freegsnke.torax_geometry_export import (
    ToraxGeometryExportAuthority,
    ToraxGeometryExportError,
    load_torax_geometry_export_authority,
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
