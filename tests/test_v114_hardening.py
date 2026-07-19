"""Honest limits, fingerprints, machine sync, passive resistivity, certify."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mast_freegsnke.certify import certify_run_dir
from mast_freegsnke.config import AppConfig
from mast_freegsnke.contracts_status import status_lines_for_run
from mast_freegsnke.honest_limits import (
    DEFAULT_HONEST_LIMITS,
    honest_limits_status_lines,
    machine_needs_rebuild,
    shot_cache_machine_fingerprints,
)
from mast_freegsnke.machine_sync import maybe_rebuild_classic_machine
from mast_freegsnke.passive_resistivity import (
    load_passive_resistivity,
    passive_resistivity_status_line,
)

REPO = Path(__file__).resolve().parents[1]
SHOT_CACHE = REPO / "data_cache" / "shot_30201"


def test_default_honest_limits_banner() -> None:
    lines = honest_limits_status_lines(None)
    assert lines[0].startswith("[INFO] Honest limits")
    assert any("CAD" in x for x in lines)
    assert any("P3/P6" in x for x in lines)
    assert len(DEFAULT_HONEST_LIMITS) >= 4


def test_passive_resistivity_awaiting() -> None:
    auth = load_passive_resistivity(REPO / "configs" / "passive_resistivity.json")
    assert auth.awaiting
    line = passive_resistivity_status_line(path="configs/passive_resistivity.json", auth=auth)
    assert "awaiting" in line.lower() or "passives" in line.lower()


def test_status_lines_for_run_include_limits() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    lines = status_lines_for_run(cfg, cwd=REPO)
    blob = "\n".join(lines)
    assert "Honest limits" in blob
    assert "passive" in blob.lower()


def test_certify_missing_run(tmp_path: Path) -> None:
    rep = certify_run_dir(tmp_path / "nope", skip_replay=True, skip_reviewer_pack=True)
    assert rep["ok"] is False
    assert rep["tier"] == "RED"


def test_certify_yellow_on_incomplete_success(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    run.mkdir()
    (run / "manifest.json").write_text(
        json.dumps({"status": "success", "blocking_errors": []}),
        encoding="utf-8",
    )
    rep = certify_run_dir(run, skip_replay=True, skip_reviewer_pack=True)
    assert rep["ok"] is True
    assert rep["tier"] in {"GREEN", "YELLOW"}
    assert (run / "CERTIFY_REPORT.json").exists()


@pytest.mark.skipif(
    not (SHOT_CACHE / "wall.zarr").exists() or not (SHOT_CACHE / "pf_active.zarr").exists(),
    reason="shot_30201 cache incomplete",
)
def test_fingerprints_and_rebuild_idempotent(tmp_path: Path) -> None:
    fps = shot_cache_machine_fingerprints(SHOT_CACHE)
    assert fps["wall"]["sha256"]
    assert fps["pf_active"]["sha256"]
    out = tmp_path / "machine"
    rep1 = maybe_rebuild_classic_machine(SHOT_CACHE, out, shot=30201, force=True)
    assert rep1["ok"] and rep1["rebuilt"]
    needs, check = machine_needs_rebuild(SHOT_CACHE, out)
    assert needs is False, check
    rep2 = maybe_rebuild_classic_machine(SHOT_CACHE, out, shot=30201, force=False)
    assert rep2["ok"] and rep2["rebuilt"] is False


def test_default_config_optional_and_rebuild() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert "wall" in cfg.required_groups
    assert "pf_passive" in cfg.optional_groups
    assert cfg.rebuild_machine_authority is True
    assert cfg.passive_resistivity_path
