"""Shot-only launcher regression tests.

The happy path must prompt for shot number(s) only; every other knob comes
from configs/default.json. These tests guard both the Python entrypoint and
the run_pipeline.* wrapper scripts against drift (e.g. stale CLI flags).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from mast_freegsnke import interactive_run

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("30201", [30201]),
        ("30201 30202", [30201, 30202]),
        ("30201,30202", [30201, 30202]),
        ("30201, 30202 30400", [30201, 30202, 30400]),
        ("30201 30201", [30201]),  # de-dupe, preserve order
    ],
)
def test_parse_shot_list(raw: str, expected: list[int]) -> None:
    assert interactive_run.parse_shot_list(raw) == expected


def test_parse_shot_list_rejects_non_digits() -> None:
    with pytest.raises(ValueError):
        interactive_run.parse_shot_list("30201 abc")


def test_interactive_run_prompts_shot_only(monkeypatch) -> None:
    prompts: list[str] = []

    def fake_input(msg: str) -> str:
        prompts.append(msg)
        return "30201"

    captured: dict = {}

    def fake_cli_main(args):
        captured["args"] = list(args)
        return 0

    def fake_assess(cfg, shot, **kw):
        from mast_freegsnke.shot_suitability import ShotSuitability

        return ShotSuitability(shot=int(shot), suitable=True)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(interactive_run.cli, "main", fake_cli_main)
    monkeypatch.setattr(interactive_run, "assess_shot_suitability", fake_assess)

    rc = interactive_run.main(["--default-config", str(REPO / "configs" / "default.json")])
    assert rc == 0
    assert len(prompts) == 1
    assert "shot" in prompts[0].lower()
    assert captured["args"][0] == "run"
    assert "--shot" in captured["args"]
    assert captured["args"][captured["args"].index("--shot") + 1] == "30201"
    assert "--machine" not in captured["args"]


def test_interactive_run_multiple_shots(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_input(msg: str) -> str:
        return "30201, 30202"

    def fake_cli_main(args):
        calls.append(list(args))
        return 0

    def fake_assess(cfg, shot, **kw):
        from mast_freegsnke.shot_suitability import ShotSuitability

        return ShotSuitability(shot=int(shot), suitable=True)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(interactive_run.cli, "main", fake_cli_main)
    monkeypatch.setattr(interactive_run, "assess_shot_suitability", fake_assess)

    rc = interactive_run.main(["--default-config", str(REPO / "configs" / "default.json")])
    assert rc == 0
    assert len(calls) == 2
    assert calls[0][calls[0].index("--shot") + 1] == "30201"
    assert calls[1][calls[1].index("--shot") + 1] == "30202"


@pytest.mark.parametrize(
    "codes,expected",
    [
        ({"1": 0, "2": 11}, 11),  # success then failure
        ({"1": 11, "2": 0}, 11),  # failure then success (must not reset)
        ({"1": 2, "2": 11}, 11),  # worst of two failures, not the first
        ({"1": 0, "2": 0}, 0),
    ],
)
def test_interactive_run_worst_exit_code(monkeypatch, codes: dict, expected: int) -> None:
    def fake_input(msg: str) -> str:
        return " ".join(codes.keys())

    def fake_cli_main(args):
        return codes[args[args.index("--shot") + 1]]

    def fake_assess(cfg, shot, **kw):
        from mast_freegsnke.shot_suitability import ShotSuitability

        return ShotSuitability(shot=int(shot), suitable=True)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(interactive_run.cli, "main", fake_cli_main)
    monkeypatch.setattr(interactive_run, "assess_shot_suitability", fake_assess)

    assert interactive_run.main(["--default-config", str(REPO / "configs" / "default.json")]) == expected


def test_interactive_run_batch_summary_lists_failed_shots(monkeypatch, capsys) -> None:
    def fake_input(msg: str) -> str:
        return "1 2 3"

    def fake_cli_main(args):
        return 11 if args[args.index("--shot") + 1] == "2" else 0

    def fake_assess(cfg, shot, **kw):
        from mast_freegsnke.shot_suitability import ShotSuitability

        return ShotSuitability(shot=int(shot), suitable=True)

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(interactive_run.cli, "main", fake_cli_main)
    monkeypatch.setattr(interactive_run, "assess_shot_suitability", fake_assess)

    rc = interactive_run.main(["--default-config", str(REPO / "configs" / "default.json")])
    out = capsys.readouterr().out
    assert rc == 11
    assert "Batch summary" in out
    assert "1/3 shots failed: 2" in out


def test_interactive_run_rejects_unknown_args() -> None:
    with pytest.raises(SystemExit) as ei:
        interactive_run.main(["--default-machine-authority", "machine_authority"])
    assert ei.value.code == 2


def test_default_config_uses_shot_dir() -> None:
    from mast_freegsnke.config import AppConfig

    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.runs_dir == Path("SHOT")
    assert cfg.execute_evolutive is True


def _extract_interactive_invocations(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if "mast_freegsnke.interactive_run" in ln and not ln.lstrip().startswith("#")]


@pytest.mark.parametrize("launcher", ["run_pipeline.cmd", "run_pipeline.sh"])
def test_launchers_pass_only_supported_flags(launcher: str) -> None:
    text = (REPO / launcher).read_text(encoding="utf-8")
    lines = _extract_interactive_invocations(text)
    assert lines, f"{launcher} must invoke mast_freegsnke.interactive_run"
    for ln in lines:
        flags = set(re.findall(r"--[a-z][a-z0-9-]*", ln))
        assert flags <= {"--default-config"}, (
            f"{launcher} passes unsupported flags to interactive_run: {sorted(flags)}"
        )


@pytest.mark.parametrize("launcher", ["run_pipeline.cmd", "run_pipeline.sh"])
def test_launchers_have_no_extra_prompts(launcher: str) -> None:
    """Wrapper scripts must not add their own y/n or path prompts."""
    text = (REPO / launcher).read_text(encoding="utf-8")
    if launcher.endswith(".sh"):
        assert "read -r -p" not in text, "run_pipeline.sh must not prompt; interactive_run owns the shot prompt"
    else:
        assert "set /p" not in text.lower(), "run_pipeline.cmd must not prompt; interactive_run owns the shot prompt"


def test_run_pipeline_cmd_always_pauses() -> None:
    text = (REPO / "run_pipeline.cmd").read_text(encoding="utf-8")
    assert "pause >nul" in text
    assert "RUN_PIPELINE_NO_PAUSE" in text
    # Must not gate pause on failure-only.
    assert 'if not "%RC%"=="0"' not in text


@pytest.mark.parametrize("launcher", ["run_pipeline.cmd", "run_pipeline.sh"])
def test_launchers_bootstrap_s5cmd_and_freegsnke_env(launcher: str) -> None:
    text = (REPO / launcher).read_text(encoding="utf-8")
    assert "ensure_s5cmd.py" in text
    assert "ensure_freegsnke_env.py" in text
    assert "RUN_PIPELINE_SKIP_FREEGSNKE_ENV" in text
    assert (REPO / "scripts" / "ensure_freegsnke_env.py").is_file()
