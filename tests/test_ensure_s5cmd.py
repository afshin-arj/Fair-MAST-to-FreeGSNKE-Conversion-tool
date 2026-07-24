"""ensure_s5cmd platform selection (no network)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_ens():
    path = ROOT / "scripts" / "ensure_s5cmd.py"
    spec = importlib.util.spec_from_file_location("ensure_s5cmd", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_release_spec_windows_amd64(tmp_path: Path) -> None:
    ens = _load_ens()
    ens.TOOLS = tmp_path
    with patch.object(ens.platform, "system", return_value="Windows"), patch.object(
        ens.platform, "machine", return_value="AMD64"
    ):
        url, target = ens._release_spec()
    assert "Windows-64bit.zip" in url
    assert target.name == "s5cmd.exe"


def test_release_spec_linux_arm64(tmp_path: Path) -> None:
    ens = _load_ens()
    ens.TOOLS = tmp_path
    with patch.object(ens.platform, "system", return_value="Linux"), patch.object(
        ens.platform, "machine", return_value="aarch64"
    ):
        url, target = ens._release_spec()
    assert "Linux-arm64.tar.gz" in url
    assert target.name == "s5cmd"


def test_release_spec_macos_arm64(tmp_path: Path) -> None:
    ens = _load_ens()
    ens.TOOLS = tmp_path
    with patch.object(ens.platform, "system", return_value="Darwin"), patch.object(
        ens.platform, "machine", return_value="arm64"
    ):
        url, target = ens._release_spec()
    assert "macOS-arm64.tar.gz" in url
    assert target.name == "s5cmd"


def test_main_skips_when_present(tmp_path: Path) -> None:
    ens = _load_ens()
    ens.TOOLS = tmp_path
    target = tmp_path / "s5cmd.exe"
    target.write_bytes(b"x" * 32)
    with patch.object(ens, "_release_spec", return_value=("https://example/s5cmd.zip", target)):
        assert ens.main() == 0
