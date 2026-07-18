"""FreeGSNKE execution must be skipped (fail-closed) when blocking errors exist.

If extract/coil-map/geometry already failed, the pipeline must not burn
FreeGSNKE compute and must record the skip explicitly in the manifest.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from mast_freegsnke import pipeline as pl
from mast_freegsnke.config import AppConfig


def _cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        mastapp_base_url="https://example.invalid/json",
        required_groups=["pf_active", "magnetics"],
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
        diagnostics_compare=[],
        diagnostic_contracts_path=None,
        diagnostic_calibration_path=None,
        coil_map_path=None,
        voltage_map_path=None,
        evolutive_authority_path=None,
        enable_contract_metrics=False,
        execute_evolutive=False,
        machine_authority_dir=None,
        require_machine_authority=False,
        provenance_hash_data=False,
        allow_cache_reuse=False,
        batch_abort_on_failure=False,
    )


def test_execute_skipped_when_blocking_errors(tmp_path: Path, monkeypatch) -> None:
    run_script_calls: list = []

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
        exists: bool = True

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
            run_script_calls.append(label)
            raise AssertionError("FreeGSNKE must not execute with blocking errors")

    monkeypatch.setattr(pl, "MastAppClient", FakeClient)
    monkeypatch.setattr(pl, "BulkDownloader", FakeDownloader)
    monkeypatch.setattr(pl, "check_groups", lambda shot, groups, discover: {g: FakeAvail() for g in groups})
    monkeypatch.setattr(pl, "Extractor", FailingExtractor)
    monkeypatch.setattr(pl, "ScriptGenerator", FakeGenerator)
    monkeypatch.setattr(pl, "FreeGSNKERunner", FakeRunner)
    monkeypatch.setattr(pl, "write_execution_authority", lambda inputs_dir, **kw: inputs_dir / "execution_authority")
    monkeypatch.setattr(pl, "write_provenance", lambda **kw: {"ok": True})
    monkeypatch.setattr(pl, "write_manifest_v2", lambda **kw: None)

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    machine_dir = tmp_path / "machine"
    machine_dir.mkdir()

    pipe = pl.ShotPipeline(cfg=_cfg(tmp_path), templates_dir=templates_dir)
    with pytest.raises(RuntimeError, match="blocking errors"):
        pipe.run(shot=99999, machine_dir=machine_dir)

    assert run_script_calls == [], "runner must never be invoked"

    manifest = json.loads((tmp_path / "SHOTS" / "99999" / "manifest.json").read_text())
    stages = {s["stage"]: s for s in manifest["stage_log"]}
    assert stages["extract_csv"]["ok"] is False
    assert stages["freegsnke_execute"]["ok"] is False
    assert stages["freegsnke_execute"]["note"] == "skipped_fail_closed_due_to_blocking_errors"
    assert any("extract_csv_failed" in e for e in manifest["blocking_errors"])
