"""P1/P2 hardening regression tests (v10.2.0).

Covers: launcher install hygiene, download cache reuse + provenance,
batch_abort_on_failure, CLI --shots batch mode, path helpers, and the honest
contract-metrics status line.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mast_freegsnke import cli
from mast_freegsnke.batch import run_shot_batch
from mast_freegsnke.config import AppConfig, cache_dir_for_shot, run_dir_for_shot
from mast_freegsnke.contracts_status import contract_metrics_status_line
from mast_freegsnke.download import (
    BulkDownloader,
    build_cache_report,
    group_cache_hit,
    group_cache_stats,
    load_prior_resolved_paths,
)

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Item 1: launcher install hygiene
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("launcher", ["run_pipeline.cmd", "run_pipeline.sh"])
def test_launchers_support_skip_install(launcher: str) -> None:
    text = (REPO / launcher).read_text(encoding="utf-8")
    assert "RUN_PIPELINE_SKIP_INSTALL" in text, f"{launcher} must honor RUN_PIPELINE_SKIP_INSTALL=1"
    assert ".install_marker" in text, f"{launcher} must use the pyproject-hash install marker"
    assert "pyproject.toml" in text


def test_cmd_launcher_marker_uses_no_prompt_read() -> None:
    """Reading the marker must not introduce set /p (would trip prompt guard)."""
    text = (REPO / "run_pipeline.cmd").read_text(encoding="utf-8")
    assert "set /p" not in text.lower()


def test_sh_launcher_has_no_pause() -> None:
    text = (REPO / "run_pipeline.sh").read_text(encoding="utf-8")
    assert "read -r -p" not in text
    assert "RUN_PIPELINE_NO_PAUSE" not in text  # POSIX terminals don't auto-close


# ---------------------------------------------------------------------------
# Item 5: path helpers
# ---------------------------------------------------------------------------

def _mk_cfg(tmp_path: Path, **over) -> AppConfig:
    kw = dict(
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
        execute_freegsnke=False,
        freegsnke_run_mode="none",
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
        allow_cache_reuse=True,
        batch_abort_on_failure=False,
    )
    kw.update(over)
    return AppConfig(**kw)


def test_path_helpers(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    assert run_dir_for_shot(cfg, 30201) == tmp_path / "SHOTS" / "30201"
    assert cache_dir_for_shot(cfg, 30201) == tmp_path / "data_cache" / "shot_30201"


def test_config_json_defaults_for_new_keys(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"level2_s3_prefix": "s3://x"}))
    cfg = AppConfig.load(p)
    assert cfg.allow_cache_reuse is True
    assert cfg.batch_abort_on_failure is False


def test_default_config_enables_cache_reuse() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.allow_cache_reuse is True
    assert cfg.batch_abort_on_failure is False


# ---------------------------------------------------------------------------
# Items 3 + 7: download cache reuse + provenance
# ---------------------------------------------------------------------------

def _populate_group(shot_dir: Path, group: str, payload: bytes = b"x" * 10) -> None:
    g = shot_dir / f"{group}.zarr"
    g.mkdir(parents=True, exist_ok=True)
    (g / "zarr.json").write_bytes(payload)


def test_group_cache_hit_and_stats(tmp_path: Path) -> None:
    shot_dir = tmp_path / "shot_1"
    assert group_cache_hit(shot_dir, "magnetics") is False
    # empty dir is not a hit
    (shot_dir / "magnetics.zarr").mkdir(parents=True)
    assert group_cache_hit(shot_dir, "magnetics") is False
    _populate_group(shot_dir, "magnetics")
    assert group_cache_hit(shot_dir, "magnetics") is True
    n, b = group_cache_stats(shot_dir, "magnetics")
    assert n == 1 and b == 10


def test_download_groups_cache_reuse_skips_s5cmd(tmp_path: Path) -> None:
    """With every group cached, download_groups must not need s5cmd or network."""
    shot_dir = tmp_path / "shot_42"
    _populate_group(shot_dir, "pf_active")
    _populate_group(shot_dir, "magnetics")
    (shot_dir / "resolved_s3_paths.json").write_text(
        json.dumps({"pf_active": "s3://bucket/42.zarr/pf_active"})
    )

    dl = BulkDownloader(
        s5cmd_path="definitely-not-a-real-s5cmd-binary",
        level2_s3_prefix="s3://bucket/shots",
        layout_patterns=["{prefix}/{shot}.zarr/{group}"],
    )
    out_dir, report = dl.download_groups(42, ["pf_active", "magnetics"], tmp_path, allow_cache_reuse=True)
    assert out_dir == shot_dir
    assert report["pf_active"]["cache_hit"] is True
    assert report["pf_active"]["s3_path"] == "s3://bucket/42.zarr/pf_active"
    assert report["magnetics"]["cache_hit"] is True
    assert report["magnetics"]["s3_path"] is None  # never recorded; honest null
    assert report["magnetics"]["n_files"] == 1
    assert report["magnetics"]["total_bytes"] == 10
    # provenance written next to the cache
    assert json.loads((shot_dir / "download_report.json").read_text())["pf_active"]["cache_hit"] is True


def test_download_groups_without_reuse_still_syncs(tmp_path: Path, monkeypatch) -> None:
    """allow_cache_reuse=False must go through discovery/sync even when cached."""
    shot_dir = tmp_path / "shot_42"
    _populate_group(shot_dir, "pf_active")
    dl = BulkDownloader(
        s5cmd_path="s5cmd",
        level2_s3_prefix="s3://bucket/shots",
        layout_patterns=["{prefix}/{shot}.zarr/{group}"],
    )

    class DiscoveryCalled(Exception):
        pass

    monkeypatch.setattr(dl, "_check_s5cmd", lambda: None)
    monkeypatch.setattr(
        dl, "discover_group_path",
        lambda shot, group: (_ for _ in ()).throw(DiscoveryCalled(group)),
    )
    with pytest.raises(DiscoveryCalled):
        dl.download_groups(42, ["pf_active"], tmp_path, allow_cache_reuse=False)


def test_build_cache_report_and_prior_paths(tmp_path: Path) -> None:
    shot_dir = tmp_path / "shot_7"
    _populate_group(shot_dir, "magnetics", payload=b"abc")
    assert load_prior_resolved_paths(shot_dir) == {}
    rep = build_cache_report(shot_dir, ["magnetics"])
    assert rep["magnetics"] == {
        "s3_path": None,
        "cache_hit": True,
        "n_files": 1,
        "total_bytes": 3,
    }


def test_pipeline_all_cached_skips_network(tmp_path: Path, monkeypatch) -> None:
    """When all groups are cache hits, no MastApp/S3 stage may touch the network."""
    from mast_freegsnke import pipeline as pl

    cfg = _mk_cfg(tmp_path)
    shot_dir = tmp_path / "data_cache" / "shot_5"
    _populate_group(shot_dir, "pf_active")
    _populate_group(shot_dir, "magnetics")

    class NetworkForbidden:
        def __init__(self, *a, **kw):
            raise AssertionError("network client must not be constructed on full cache hit")

    monkeypatch.setattr(pl, "MastAppClient", NetworkForbidden)
    monkeypatch.setattr(pl, "BulkDownloader", NetworkForbidden)

    class FailingExtractor:
        def __init__(self, **kw):
            pass

        def extract(self, shot_cache, inputs_dir):
            raise RuntimeError("stop here; cache stages already exercised")

    class FakeGenerator:
        def __init__(self, templates_dir):
            pass

        def generate(self, run_dir, machine_dir, formed_frac):
            return None

    monkeypatch.setattr(pl, "Extractor", FailingExtractor)
    monkeypatch.setattr(pl, "ScriptGenerator", FakeGenerator)
    monkeypatch.setattr(pl, "write_execution_authority", lambda inputs_dir, **kw: inputs_dir / "execution_authority")
    monkeypatch.setattr(pl, "write_provenance", lambda **kw: {"ok": True})
    monkeypatch.setattr(pl, "write_manifest_v2", lambda **kw: None)

    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
    machine_dir = tmp_path / "machine"
    machine_dir.mkdir()

    pipe = pl.ShotPipeline(cfg=cfg, templates_dir=templates_dir)
    with pytest.raises(RuntimeError, match="blocking errors"):
        pipe.run(shot=5, machine_dir=machine_dir)

    manifest = json.loads((tmp_path / "SHOTS" / "5" / "manifest.json").read_text())
    stages = {s["stage"]: s for s in manifest["stage_log"]}
    assert stages["mastapp_shot_exists"]["note"] == "skipped_all_groups_cached"
    assert stages["s3_shot_preflight"]["note"] == "skipped_all_groups_cached"
    assert stages["download_groups"]["cache_hits"] == ["magnetics", "pf_active"]
    assert manifest["download_report"]["pf_active"]["cache_hit"] is True


# ---------------------------------------------------------------------------
# Items 4 + 6: batch semantics (shared loop) + CLI --shots
# ---------------------------------------------------------------------------

def test_run_shot_batch_worst_code_no_abort(tmp_path: Path, capsys) -> None:
    codes = {1: 0, 2: 11, 3: 2}
    ran: list[int] = []

    def run_one(s: int) -> int:
        ran.append(s)
        return codes[s]

    rc = run_shot_batch([1, 2, 3], run_one, runs_dir=tmp_path, abort_on_failure=False)
    out = capsys.readouterr().out
    assert rc == 11
    assert ran == [1, 2, 3]
    assert "Batch summary" in out
    assert "2/3 shots failed: 2, 3" in out


def test_run_shot_batch_abort_on_failure(tmp_path: Path, capsys) -> None:
    ran: list[int] = []

    def run_one(s: int) -> int:
        ran.append(s)
        return 11 if s == 2 else 0

    rc = run_shot_batch([1, 2, 3], run_one, runs_dir=tmp_path, abort_on_failure=True)
    out = capsys.readouterr().out
    assert rc == 11
    assert ran == [1, 2]  # shot 3 skipped
    assert "skipping remaining shots: 3" in out
    assert "[SKIP] shot 3" in out


def test_interactive_batch_abort_on_failure(monkeypatch, tmp_path: Path) -> None:
    """Interactive launcher honors batch_abort_on_failure from config."""
    from mast_freegsnke import interactive_run

    base = json.loads((REPO / "configs" / "default.json").read_text())
    base["batch_abort_on_failure"] = True
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(base))

    calls: list[str] = []

    def fake_cli_main(args):
        shot = args[args.index("--shot") + 1]
        calls.append(shot)
        return 11 if shot == "2" else 0

    monkeypatch.setattr("builtins.input", lambda msg: "1 2 3")
    monkeypatch.setattr(interactive_run.cli, "main", fake_cli_main)

    rc = interactive_run.main(["--default-config", str(cfg_path)])
    assert rc == 11
    assert calls == ["1", "2"]


def test_cli_run_rejects_shot_and_shots_together(tmp_path: Path) -> None:
    rc = cli.main([
        "run", "--config", str(REPO / "configs" / "default.json"),
        "--shot", "1", "--shots", "2", "3",
    ])
    assert rc == 2


def test_cli_run_rejects_missing_shot_args() -> None:
    rc = cli.main(["run", "--config", str(REPO / "configs" / "default.json")])
    assert rc == 2


def test_cli_run_shots_batch(monkeypatch, tmp_path: Path, capsys) -> None:
    ran: list[int] = []

    class FakePipeline:
        def __init__(self, cfg, templates_dir):
            self.cfg = cfg

        def run(self, shot, machine_dir, tstart=None, tend=None):
            ran.append(int(shot))
            run_dir = tmp_path / str(shot)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "manifest.json").write_text(json.dumps({"status": "success", "blocking_errors": []}))
            return run_dir

    monkeypatch.setattr(cli, "ShotPipeline", FakePipeline)
    rc = cli.main([
        "run", "--config", str(REPO / "configs" / "default.json"),
        "--shots", "101", "102",
    ])
    out = capsys.readouterr().out
    assert rc == 0
    assert ran == [101, 102]
    assert "Batch summary" in out


# ---------------------------------------------------------------------------
# Item 2 (honest branch): contract metrics status line
# ---------------------------------------------------------------------------

def test_contract_status_line_disabled(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path)
    line = contract_metrics_status_line(cfg)
    assert line is not None
    assert "disabled" in line
    assert "diagnostic" in line.lower()


def test_contract_status_line_enabled_without_path(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path, enable_contract_metrics=True)
    line = contract_metrics_status_line(cfg)
    assert line is not None and "diagnostic_contracts_path" in line


def test_contract_status_line_fully_wired(tmp_path: Path) -> None:
    cfg = _mk_cfg(tmp_path, enable_contract_metrics=True, diagnostic_contracts_path="x.json")
    assert contract_metrics_status_line(cfg) is None


def test_interactive_prints_contract_status(monkeypatch, capsys) -> None:
    from mast_freegsnke import interactive_run

    monkeypatch.setattr("builtins.input", lambda msg: "30201")
    monkeypatch.setattr(interactive_run.cli, "main", lambda args: 0)
    rc = interactive_run.main(["--default-config", str(REPO / "configs" / "default.json")])
    out = capsys.readouterr().out
    assert rc == 0
    # v10.3.0: default.json ships real contracts + enable_contract_metrics=true,
    # so the status line is omitted (fully wired). Still print the enable flag.
    assert "enable_contract_metrics=True" in out
    assert "Contract residual metrics disabled" not in out
