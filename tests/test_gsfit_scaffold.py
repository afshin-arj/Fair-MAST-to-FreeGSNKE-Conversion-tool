"""ADR-006 GSFit live peer scaffold — readiness gate and soft-skip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mast_freegsnke.gsfit_stage import (
    GsfitAuthorityError,
    gsfit_readiness,
    load_gsfit_authority,
    run_gsfit_stage,
    write_gsfit_authority,
)


REPO = Path(__file__).resolve().parents[1]


def test_load_shipped_authority_awaiting():
    auth = load_gsfit_authority(REPO / "configs" / "gsfit_authority.json")
    assert auth.status_awaiting
    assert auth.require is False
    assert auth.feed_targets_from_gsfit is False
    assert auth.output_relpath == "08_gsfit"


def test_missing_authority_fail_closed(tmp_path: Path):
    with pytest.raises(GsfitAuthorityError, match="not found"):
        load_gsfit_authority(tmp_path / "missing.json")


def test_readiness_false_while_calib_awaiting():
    auth = load_gsfit_authority(REPO / "configs" / "gsfit_authority.json")
    ready = gsfit_readiness(auth, repo_root=REPO, check_import=False)
    assert ready.ready is False
    assert ready.status == "awaiting_authority"
    assert "diagnostic_calibration_awaiting" in ready.blocking
    assert "greens_authority_awaiting" in ready.blocking
    assert "settings_pack_awaiting" in ready.blocking


def test_soft_skip_writes_gsfit_json(tmp_path: Path):
    auth = load_gsfit_authority(REPO / "configs" / "gsfit_authority.json")
    run_dir = tmp_path / "SHOT" / "99999"
    run_dir.mkdir(parents=True)
    rep = run_gsfit_stage(run_dir, shot=99999, auth=auth, repo_root=REPO)
    assert rep.ok is False
    assert rep.status == "awaiting_authority"
    out = run_dir / "08_gsfit" / "GSFIT.json"
    assert out.is_file()
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert obj["ok"] is False
    assert obj["status"] == "awaiting_authority"
    assert "readiness" in obj
    assert (run_dir / "08_gsfit" / "GSFIT.md").is_file()


def test_write_authority_snapshot(tmp_path: Path):
    auth = load_gsfit_authority(REPO / "configs" / "gsfit_authority.json")
    path = write_gsfit_authority(tmp_path / "inputs", auth)
    assert path.is_file()
    again = load_gsfit_authority(path)
    assert again.status == auth.status


def test_ready_path_with_mock_solve(tmp_path: Path, monkeypatch):
    """Mock prerequisites + solve_fn — never invents metrology or calls Rust."""
    # Temporary ready authority + fake prereq trees under tmp
    calib = {
        "version": "1.0",
        "status": "populated",
        "channels": {
            "OMV_1": {
                "exp_column": "x",
                "source_variable": "y",
                "units_in": "V",
                "units_out": "T",
                "scale": 1.0,
                "sign": 1,
                "source": "unit-test-citation",
                "notes": "test only",
            }
        },
    }
    greens_dir = tmp_path / "greens"
    greens_dir.mkdir()
    (greens_dir / "provenance.json").write_text(
        json.dumps(
            {
                "status": "cited",
                "source": "unit-test DOI",
                "files": [{"name": "dummy.npz", "sha256": "abc"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    (settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "sensors": {
                    "bp_probes": {"include": ["P1"], "weights": {"P1": 1.0}},
                    "flux_loops": {"include": ["FL1"], "weights": {"FL1": 1.0}},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    geom = {"flux_loops": [{"name": "FL1", "r_m": 1.0, "z_m": 0.0, "turns": 1}]}
    calib_path = tmp_path / "calib.json"
    geom_path = tmp_path / "geom.json"
    calib_path.write_text(json.dumps(calib) + "\n", encoding="utf-8")
    geom_path.write_text(json.dumps(geom) + "\n", encoding="utf-8")

    auth_obj = {
        "authority_name": "gsfit",
        "authority_version": "1.0",
        "status": "ready",
        "require": False,
        "feed_targets_from_gsfit": False,
        "diagnostic_calibration_path": str(calib_path),
        "greens_authority_path": str(greens_dir),
        "settings_pack_path": str(settings_dir),
        "probe_geometry_path": str(geom_path),
        "passive_resistivity_path": str(
            REPO / "configs" / "passive_resistivity.json"
        ),
        "output_relpath": "08_gsfit",
        "awaiting": [],
    }
    auth_path = tmp_path / "gsfit_authority.json"
    auth_path.write_text(json.dumps(auth_obj) + "\n", encoding="utf-8")
    auth = load_gsfit_authority(auth_path)

    def _fake_solve(ctx):
        out = Path(ctx["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        fake = out / "fake_lcfs.csv"
        fake.write_text("r,z\n1,0\n", encoding="utf-8")
        return {
            "ok": True,
            "status": "ok",
            "errors": [],
            "fix_hint": "",
            "files_written": [str(fake)],
        }

    # Bypass import check by patching readiness path: run_gsfit_stage calls
    # gsfit_readiness with check_import=True. Monkeypatch check_gsfit_import.
    from mast_freegsnke import gsfit_stage as mod

    monkeypatch.setattr(
        mod,
        "check_gsfit_import",
        lambda: {
            "ok": True,
            "id": "gsfit_import",
            "status": "installed",
            "detail": "mocked",
            "version": "test",
        },
    )

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rep = run_gsfit_stage(
        run_dir, shot=1, auth=auth, repo_root=tmp_path, solve_fn=_fake_solve
    )
    assert rep.ok is True
    assert rep.status == "ok"
    obj = json.loads((run_dir / "08_gsfit" / "GSFIT.json").read_text(encoding="utf-8"))
    assert obj["ok"] is True


def test_config_requires_authority_path(tmp_path: Path):
    from mast_freegsnke.config import AppConfig

    base = json.loads((REPO / "configs" / "default.json").read_text(encoding="utf-8"))
    base["execute_gsfit"] = True
    base["gsfit_authority_path"] = None
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(base), encoding="utf-8")
    with pytest.raises(ValueError, match="gsfit_authority_path"):
        AppConfig.load(p)


def test_default_config_gsfit_on():
    from mast_freegsnke.config import AppConfig

    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.execute_gsfit is True
    assert cfg.gsfit_authority_path == "configs/gsfit_authority.json"


def test_certify_warns_awaiting(tmp_path: Path):
    from mast_freegsnke.certify import certify_run_dir

    run_dir = tmp_path / "30201"
    (run_dir / "08_gsfit").mkdir(parents=True)
    (run_dir / "08_gsfit" / "GSFIT.json").write_text(
        json.dumps(
            {
                "ok": False,
                "status": "awaiting_authority",
                "require": False,
                "authority_version": "1.0",
                "readiness": {"status": "awaiting_authority"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps({"shot": 30201, "status": "success", "stages": [], "blocking_errors": []})
        + "\n",
        encoding="utf-8",
    )
    report = certify_run_dir(run_dir, skip_replay=True, skip_reviewer_pack=True)
    assert "gsfit_awaiting_authority" in (report.get("warnings") or [])


def test_ui_load_gsfit(tmp_path: Path):
    from mast_freegsnke_ui import artifacts as art

    run_dir = tmp_path / "shot"
    (run_dir / "08_gsfit").mkdir(parents=True)
    payload = {"ok": False, "status": "awaiting_authority", "label": "test"}
    (run_dir / "08_gsfit" / "GSFIT.json").write_text(
        json.dumps(payload) + "\n", encoding="utf-8"
    )
    loaded = art.load_gsfit(run_dir)
    assert loaded is not None
    assert loaded["status"] == "awaiting_authority"
