"""Shot suitability gate + batch skip-to-next."""
from __future__ import annotations

from pathlib import Path

import pytest

from mast_freegsnke.batch import run_shot_batch
from mast_freegsnke.config import AppConfig
from mast_freegsnke.shot_suitability import (
    EXIT_UNSUITABLE,
    ShotSuitability,
    assess_shot_suitability,
    format_unsuitable_message,
)
from mast_freegsnke import interactive_run

REPO = Path(__file__).resolve().parents[1]


def _cfg(tmp_path: Path, **over) -> AppConfig:
    kw = dict(
        mastapp_base_url="https://example.invalid/json",
        required_groups=["pf_active", "magnetics", "wall"],
        optional_groups=[],
        level2_s3_prefix="s3://bucket/shots",
        s5cmd_path="s5cmd",
        s3_endpoint_url=None,
        s3_no_sign_request=True,
        s5cmd_timeout_s=5,
        runs_dir=tmp_path / "SHOT",
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
        allow_cache_reuse=True,
        batch_abort_on_failure=False,
        enable_shot_suitability_gate=True,
    )
    kw.update(over)
    return AppConfig(**kw)


def test_format_unsuitable_message_is_professional() -> None:
    rep = ShotSuitability(
        shot=99999,
        suitable=False,
        reasons=["Required FAIR-MAST Level-2 groups are missing: wall"],
        hints=["Try shot 30201."],
    )
    msg = format_unsuitable_message(rep)
    assert "99999" in msg
    assert "not suitable" in msg.lower()
    assert "Reasons:" in msg
    assert "What you can do:" in msg
    assert "😊" not in msg


def test_cache_hit_makes_shot_suitable(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    shot_dir = tmp_path / "data_cache" / "shot_30201"
    for g in cfg.required_groups:
        d = shot_dir / f"{g}.zarr"
        d.mkdir(parents=True)
        (d / "zarr.json").write_text("{}", encoding="utf-8")
    rep = assess_shot_suitability(cfg, 30201)
    assert rep.suitable is True
    assert rep.checks.get("decision") == "all_required_groups_cached"


def test_invalid_shot_number_unsuitable(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    rep = assess_shot_suitability(cfg, 0)
    assert rep.suitable is False
    assert any("positive" in r.lower() for r in rep.reasons)


def test_batch_skips_unsuitable_and_continues(tmp_path: Path, capsys) -> None:
    calls: list[int] = []

    def run_one(shot: int) -> int:
        calls.append(shot)
        return 0

    def suitability(shot: int) -> ShotSuitability:
        if shot == 2:
            return ShotSuitability(
                shot=2,
                suitable=False,
                reasons=["missing Level-2 groups"],
                hints=["try another"],
            )
        return ShotSuitability(shot=shot, suitable=True)

    rc = run_shot_batch(
        [1, 2, 3],
        run_one,
        runs_dir=tmp_path,
        abort_on_failure=False,
        suitability=suitability,
    )
    out = capsys.readouterr().out
    assert calls == [1, 3]
    assert rc == 0
    assert "not suitable" in out.lower()
    assert "Moving to the next shot" in out
    assert "[SKIP] shot 2" in out


def test_batch_all_unsuitable_returns_exit_20(tmp_path: Path) -> None:
    def run_one(shot: int) -> int:
        raise AssertionError("must not run")

    def suitability(shot: int) -> ShotSuitability:
        return ShotSuitability(shot=shot, suitable=False, reasons=["no"], hints=[])

    rc = run_shot_batch([9, 8], run_one, runs_dir=tmp_path, suitability=suitability)
    assert rc == EXIT_UNSUITABLE


def test_unsuitable_does_not_trigger_abort(tmp_path: Path) -> None:
    calls: list[int] = []

    def run_one(shot: int) -> int:
        calls.append(shot)
        return 0

    def suitability(shot: int) -> ShotSuitability:
        return ShotSuitability(
            shot=shot,
            suitable=(shot != 1),
            reasons=["bad"] if shot == 1 else [],
        )

    rc = run_shot_batch(
        [1, 2, 3],
        run_one,
        runs_dir=tmp_path,
        abort_on_failure=True,
        suitability=suitability,
    )
    assert calls == [2, 3]
    assert rc == 0


def test_interactive_reprompts_when_single_unsuitable(monkeypatch) -> None:
    prompts: list[str] = []
    inputs = iter(["99999", "30201"])

    def fake_input(msg: str) -> str:
        prompts.append(msg)
        return next(inputs)

    def fake_assess(cfg, shot, **kw):
        if int(shot) == 99999:
            return ShotSuitability(
                shot=99999,
                suitable=False,
                reasons=["not listed"],
                hints=["try 30201"],
            )
        return ShotSuitability(shot=int(shot), suitable=True)

    captured: list[list[str]] = []

    def fake_cli_main(args):
        captured.append(list(args))
        return 0

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(interactive_run, "assess_shot_suitability", fake_assess)
    monkeypatch.setattr(interactive_run.cli, "main", fake_cli_main)

    rc = interactive_run.main(["--default-config", str(REPO / "configs" / "default.json")])
    assert rc == 0
    assert len(prompts) == 2
    assert captured[-1][captured[-1].index("--shot") + 1] == "30201"


def test_interactive_multi_skips_unsuitable(monkeypatch, capsys) -> None:
    def fake_input(msg: str) -> str:
        return "1 30201 2"

    def fake_assess(cfg, shot, **kw):
        ok = int(shot) == 30201
        return ShotSuitability(
            shot=int(shot),
            suitable=ok,
            reasons=[] if ok else ["missing"],
            hints=[],
        )

    calls: list[str] = []

    def fake_cli_main(args):
        calls.append(args[args.index("--shot") + 1])
        return 0

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(interactive_run, "assess_shot_suitability", fake_assess)
    monkeypatch.setattr(interactive_run.cli, "main", fake_cli_main)

    rc = interactive_run.main(["--default-config", str(REPO / "configs" / "default.json")])
    out = capsys.readouterr().out
    assert rc == 0
    assert calls == ["30201"]
    assert "continuing with the remaining" in out.lower() or "SKIP" in out


def test_default_config_enables_suitability_gate() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.enable_shot_suitability_gate is True
