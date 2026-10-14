"""Regression tests for the v11.35.1 audit fixes.

Covers:
- planner limitation interpolation (no raw f-string field references leak) and
  the policy-conditional voltage-limit claim (fail-closed vs measured_peak).
- coil_map SHA-256 snapshot at write time (binding mapping authority).
- run-config snapshot + hash into 06_authorities/config/ (root authority).
- shot_summary authority lines: file_hashes.json (corrected name), coil_map
  sha, config sha.
- pipeline honesty when an authority snapshot fails with executors off:
  stage ok=False + degraded note (never ok=True).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import mast_freegsnke
from mast_freegsnke.coil_map import load_coil_map, snapshot_coil_map_hash
from mast_freegsnke.config import AppConfig
from mast_freegsnke.planner import voltage_limitation_claim
from mast_freegsnke.shot_summary import write_shot_expert_overlay

REPO = Path(__file__).resolve().parents[1]


def test_version_is_consistent_across_packaging_and_docs() -> None:
    """Drift guard: package version must match pyproject + version tables in docs
    (the 11.35.1 audit shipped with the bump forgotten in the first commit)."""
    ver = mast_freegsnke.__version__
    m = re.search(r'^version = "([^"]+)"', (REPO / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    assert m, "pyproject.toml version field missing"
    assert m.group(1) == ver, f"pyproject {m.group(1)} != package {ver}"
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert f"**Version** | **{ver}**" in readme, "README version table drifted"
    manual = (REPO / "docs" / "USER_MANUAL.md").read_text(encoding="utf-8")
    assert f"**Version:** {ver}" in manual, "USER_MANUAL version drifted"
    changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {ver} " in changelog, f"CHANGELOG missing top entry for {ver}"


# ---------------------------------------------------------------------------
# Planner: limitation interpolation + policy-conditional voltage claim (#1/#7)
# ---------------------------------------------------------------------------


def test_voltage_limitation_claim_is_policy_conditional() -> None:
    fail_closed = voltage_limitation_claim("cited_plant_limits")
    assert "fail-closed" in fail_closed
    assert "measured_peak_margin" not in fail_closed

    soft = voltage_limitation_claim("measured_peak_margin")
    assert "measured_peak_margin" in soft
    assert "voltage_exceeds_measured_peak_margin" in soft
    assert "not a plant rating" in soft
    # The old unconditional claim must not survive for the soft policy.
    assert "over-limit plans raise PlannerError" not in soft


def test_voltage_limitation_claim_default_is_fail_closed() -> None:
    for policy in (None, "", "other_policy"):
        assert "fail-closed" in voltage_limitation_claim(policy)


# ---------------------------------------------------------------------------
# Coil map: resolved snapshot is hashed at write time (#8)
# ---------------------------------------------------------------------------


def test_snapshot_coil_map_hash_writes_matching_digest(tmp_path: Path) -> None:
    coil_map = load_coil_map(REPO / "configs" / "coil_map.json")
    run = tmp_path / "run"
    run.mkdir()

    meta = snapshot_coil_map_hash(coil_map, run)

    resolved = run / "contracts" / "coil_map.resolved.json"
    side = run / "contracts" / "coil_map.sha256.json"
    assert resolved.is_file()
    assert side.is_file()
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    assert meta["sha256"] == digest
    assert meta["path"] == "contracts/coil_map.resolved.json"
    assert json.loads(side.read_text(encoding="utf-8"))["sha256"] == digest


# ---------------------------------------------------------------------------
# Config: load() records its source file for snapshot+hash (#9)
# ---------------------------------------------------------------------------


def test_appconfig_load_records_source_path() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.source_path == str((REPO / "configs" / "default.json").resolve())
    # dataclasses.replace() preserves the record (used to redirect runs_dir etc.).
    replaced = dataclasses.replace(cfg, runs_dir=Path("some/other/runs"))
    assert replaced.source_path == cfg.source_path


# ---------------------------------------------------------------------------
# shot_summary: corrected provenance name + new hash lines (#3/#8/#9)
# ---------------------------------------------------------------------------


def test_summary_lists_corrected_and_new_authority_hashes(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    (run / "01_summary").mkdir(parents=True)
    (run / "inputs").mkdir()
    (run / "inputs" / "window.json").write_text(
        json.dumps({"t_start": 0.2, "t_end": 0.4}) + "\n", encoding="utf-8"
    )

    # Fix #3: the dead "hashes.json" probe must now name the real file.
    (run / "provenance").mkdir()
    (run / "provenance" / "file_hashes.json").write_text(
        json.dumps({"files": {}}) + "\n", encoding="utf-8"
    )

    # Fix #8: coil_map sha line.
    (run / "contracts").mkdir()
    coil_digest = "a" * 64
    (run / "contracts" / "coil_map.sha256.json").write_text(
        json.dumps({"path": "contracts/coil_map.resolved.json", "sha256": coil_digest}) + "\n",
        encoding="utf-8",
    )

    # Fix #9: run-config sha line (post-layout location).
    cfg_dir = run / "06_authorities" / "config"
    cfg_dir.mkdir(parents=True)
    cfg_digest = "b" * 64
    (cfg_dir / "config.sha256.json").write_text(
        json.dumps({"path": "config_snapshot/default.json", "sha256": cfg_digest}) + "\n",
        encoding="utf-8",
    )

    manifest: dict[str, Any] = {"shot": 30201, "status": "success", "stage_log": []}
    write_shot_expert_overlay(run, shot=30201, manifest=manifest, science_audit={})
    md = (run / "01_summary" / "SUMMARY.md").read_text(encoding="utf-8")

    assert "provenance/file_hashes.json" in md
    assert "hashes.json" not in md.replace("file_hashes.json", "")
    assert "coil_map sha256" in md and coil_digest[:16] in md
    assert "config sha256" in md and cfg_digest[:16] in md


# ---------------------------------------------------------------------------
# Pipeline: config snapshot stage + planner snapshot-failure honesty (#6/#9)
# ---------------------------------------------------------------------------


def _cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        mastapp_base_url="https://example.invalid/json",
        required_groups=["pf_active", "magnetics"],
        optional_groups=[],
        level2_s3_prefix="s3://bucket/shots",
        s5cmd_path="s5cmd",
        s3_endpoint_url=None,
        s3_no_sign_request=True,
        s5cmd_timeout_s=5,
        runs_dir=tmp_path / "SHOTS",
        cache_dir=tmp_path / "data_cache",
        formed_plasma_frac=0.8,
        s3_layout_patterns=["{prefix}/{shot}.zarr/{group}"],
        allow_missing_geometry=True,
        execute_freegsnke=True,
        freegsnke_run_mode="both",
        freegsnke_python=None,
        diagnostic_contracts_path=None,
        diagnostic_calibration_path=None,
        coil_map_path=None,
        voltage_map_path=None,
        evolutive_authority_path=None,
        passive_resistivity_path=None,
        enable_contract_metrics=False,
        enable_experimental_data=False,
        experimental_data_plots=False,
        experimental_data_include_l1=False,
        experimental_data_include_l3=False,
        execute_evolutive=False,
        machine_authority_dir=None,
        require_machine_authority=False,
        rebuild_machine_authority=False,
        provenance_hash_data=False,
        allow_cache_reuse=False,
        batch_abort_on_failure=False,
        enable_shot_suitability_gate=False,
    )


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Minimal fake harness so pipe.run() reaches authority snapshot stages."""
    from mast_freegsnke import pipeline as pl

    class FakeClient:
        def __init__(self, base_url):
            pass

        def shot_exists(self, shot):
            return True

    class FakeDownloader:
        def __init__(self, **kw):
            pass

        def preflight(self, shot):
            return None

        def discover_group_path(self, shot, group):
            return f"s3://bucket/shots/{shot}.zarr/{group}"

        def download_groups(self, shot, groups, cache_root, allow_cache_reuse=False):
            d = Path(cache_root) / f"shot_{shot}"
            d.mkdir(parents=True, exist_ok=True)
            report = {g: {"s3_path": None, "cache_hit": False, "n_files": 0, "total_bytes": 0} for g in groups}
            return d, report

    @dataclass
    class FakeAvail:
        group: str = ""
        exists: bool = True
        s3_path: str = "s3://bucket/fake"
        error: object = None

    class FailingExtractor:
        def __init__(self, **kw):
            pass

        def extract(self, shot_cache, inputs_dir):
            raise RuntimeError("simulated extract failure")

    class FakeGenerator:
        def __init__(self, templates_dir):
            pass

        def generate(self, run_dir, machine_dir, formed_frac):
            return None

    class FakeRunner:
        def __init__(self, python_exe=None, timeout_s=None, **kwargs):
            pass

        def run_script(self, script, run_dir, label):
            raise AssertionError("FreeGSNKE must not execute in this harness")

    def _fake_avail(*, shot, groups, discover, shot_cache, allow_cache_reuse):
        return {g: FakeAvail(group=g) for g in groups}

    monkeypatch.setattr(pl, "MastAppClient", FakeClient)
    monkeypatch.setattr(pl, "BulkDownloader", FakeDownloader)
    monkeypatch.setattr(pl, "check_groups_respecting_cache", _fake_avail)
    monkeypatch.setattr(pl, "Extractor", FailingExtractor)
    monkeypatch.setattr(pl, "ScriptGenerator", FakeGenerator)
    monkeypatch.setattr(pl, "FreeGSNKERunner", FakeRunner)
    monkeypatch.setattr(pl, "write_execution_authority", lambda inputs_dir, **kw: inputs_dir / "execution_authority")
    monkeypatch.setattr(pl, "write_provenance", lambda **kw: {"ok": True})
    monkeypatch.setattr(pl, "write_manifest_v2", lambda **kw: None)


def _run_and_load_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cfg: AppConfig) -> dict:
    from mast_freegsnke import pipeline as pl

    _install_fakes(monkeypatch)
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir(exist_ok=True)
    machine_dir = tmp_path / "machine"
    machine_dir.mkdir(exist_ok=True)

    pipe = pl.ShotPipeline(cfg=cfg, templates_dir=templates_dir)
    with pytest.raises(RuntimeError, match="blocking errors"):
        pipe.run(shot=99999, machine_dir=machine_dir)

    manifest_path = tmp_path / "SHOTS" / "99999" / "manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def test_pipeline_snapshots_and_hashes_run_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_file = tmp_path / "audit_config.json"
    cfg_file.write_text(json.dumps({"declared": "root authority"}), encoding="utf-8")
    cfg = dataclasses.replace(_cfg(tmp_path), source_path=str(cfg_file))

    manifest = _run_and_load_manifest(tmp_path, monkeypatch, cfg)

    stages = {s["stage"]: s for s in manifest["stage_log"]}
    assert "config_snapshot" in stages
    stage = stages["config_snapshot"]
    assert stage["ok"] is True
    digest = stage["sha256"]
    assert isinstance(digest, str) and len(digest) == 64

    # Layout moves config_snapshot/ -> 06_authorities/config/ (junction back).
    run_dir = tmp_path / "SHOTS" / "99999"
    post = run_dir / "06_authorities" / "config" / "config.sha256.json"
    pre = run_dir / "config_snapshot" / "config.sha256.json"
    sha_path = post if post.is_file() else pre
    assert sha_path.is_file(), "run config hash must be written"
    meta = json.loads(sha_path.read_text(encoding="utf-8"))
    copied = sha_path.parent / cfg_file.name
    assert copied.is_file(), "run config copy must exist next to its hash"
    assert meta["sha256"] == hashlib.sha256(copied.read_bytes()).hexdigest() == digest

    # Manifest payload carries the snapshot record for provenance.
    assert isinstance(manifest.get("config_snapshot"), dict)
    assert manifest["config_snapshot"]["sha256"] == digest


def test_pipeline_config_source_path_none_is_soft(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _run_and_load_manifest(tmp_path, monkeypatch, _cfg(tmp_path))
    stages = {s["stage"]: s for s in manifest["stage_log"]}
    stage = stages["config_snapshot"]
    assert stage["ok"] is True
    assert stage.get("note") == "no_config_source_path"
    assert manifest.get("config_snapshot") is None
    assert not (tmp_path / "SHOTS" / "99999" / "06_authorities" / "config").exists()


def test_planner_authority_snapshot_failure_is_degraded_not_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "planner_authority_bad.json"
    bad.write_text("{ this is not valid json", encoding="utf-8")
    cfg = dataclasses.replace(_cfg(tmp_path), planner_authority_path=str(bad))

    manifest = _run_and_load_manifest(tmp_path, monkeypatch, cfg)

    stages = {s["stage"]: s for s in manifest["stage_log"]}
    # Fix #6: an authority snapshot failure must never be reported ok=True.
    stage = stages["planner_authority"]
    assert stage["ok"] is False
    assert stage.get("note", "").startswith("snapshot_failed:")
    # And it must be surfaced as a degraded note (manifest everything).
    notes = manifest.get("degraded_notes") or []
    assert any(str(n).startswith("planner_authority_snapshot_failed:") for n in notes)
