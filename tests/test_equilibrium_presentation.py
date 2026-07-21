"""Tests for equilibrium presentation (PNG stitch → GIF)."""

from __future__ import annotations

from pathlib import Path

import pytest

from mast_freegsnke.equilibrium_presentation import (
    PresentationAuthority,
    PresentationError,
    load_presentation_authority,
    presentation_gifs_under,
    write_gif_from_pngs,
    write_presentation_authority,
)


def test_presentation_authority_roundtrip(tmp_path: Path) -> None:
    auth = PresentationAuthority(write_equilibrium_gifs=True, gif_fps=2.5, gif_dpi=120)
    path = write_presentation_authority(tmp_path, auth)
    loaded = load_presentation_authority(path)
    assert loaded.write_equilibrium_gifs is True
    assert loaded.gif_fps == pytest.approx(2.5)
    assert loaded.gif_dpi == 120


def test_presentation_authority_rejects_gif_without_frames() -> None:
    with pytest.raises(PresentationError):
        PresentationAuthority(write_equilibrium_gifs=True, write_eq_frames=False).validate()


def test_write_gif_from_pngs(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image

    frames = []
    for i, color in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)]):
        p = tmp_path / f"frame_{i:02d}.png"
        Image.new("RGB", (32, 48), color).save(p)
        frames.append(p)
    out = tmp_path / "out.gif"
    rep = write_gif_from_pngs(frames, out, fps=2.0)
    assert rep["ok"], rep
    assert out.exists()
    assert out.stat().st_size > 0
    assert rep["n_frames"] == 3


def test_write_gif_needs_two_frames(tmp_path: Path) -> None:
    pytest.importorskip("PIL")
    from PIL import Image

    p = tmp_path / "only.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(p)
    rep = write_gif_from_pngs([p], tmp_path / "x.gif", fps=1.0)
    assert not rep["ok"]
    assert any("need_at_least_2_frames" in e for e in rep["errors"])


def test_presentation_gifs_under(tmp_path: Path) -> None:
    (tmp_path / "presentation").mkdir()
    (tmp_path / "presentation" / "inverse_equilibria.gif").write_bytes(b"GIF89a")
    (tmp_path / "evolutive").mkdir()
    (tmp_path / "evolutive" / "evolutive_equilibria.gif").write_bytes(b"GIF89a")
    found = presentation_gifs_under(tmp_path)
    assert found["inverse"] == "presentation/inverse_equilibria.gif"
    assert found["evolutive"] == "evolutive/evolutive_equilibria.gif"
    assert "forward" not in found
