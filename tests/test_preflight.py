"""Happy-path preflight (interactive + doctor alignment)."""
from __future__ import annotations

from pathlib import Path

from mast_freegsnke.config import AppConfig
from mast_freegsnke.preflight import collect_happy_path_failures

REPO = Path(__file__).resolve().parents[1]


def test_shipped_default_preflight_ok_when_envs_present() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    fails = collect_happy_path_failures(cfg, REPO)
    # On CI / fresh clone without .venv-freegsnke this may fail — only assert
    # that returned items are strings (and machine/coil/voltage/contracts exist).
    assert isinstance(fails, list)
    # Authority files shipped in repo must not be the reason.
    for f in fails:
        assert "coil_map invalid" not in f
        assert "voltage_map invalid" not in f
        assert "diagnostic_contracts invalid" not in f
        assert "machine authority invalid" not in f


def test_preflight_flags_missing_coil_map(tmp_path: Path) -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    object.__setattr__(cfg, "coil_map_path", str(tmp_path / "missing_coil_map.json"))
    object.__setattr__(cfg, "execute_freegsnke", False)
    object.__setattr__(cfg, "execute_evolutive", False)
    object.__setattr__(cfg, "enable_contract_metrics", False)
    object.__setattr__(cfg, "require_machine_authority", False)
    object.__setattr__(cfg, "s5cmd_path", "s5cmd_definitely_missing_xyz")
    fails = collect_happy_path_failures(cfg, tmp_path)
    assert any("coil_map_path missing" in f for f in fails)
