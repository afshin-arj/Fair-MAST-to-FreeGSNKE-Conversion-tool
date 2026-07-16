"""Shot-only launcher regression tests.

The happy path must prompt for the shot number only; every other knob comes
from configs/default.json. These tests guard both the Python entrypoint and
the run_pipeline.* wrapper scripts against drift (e.g. stale CLI flags).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from mast_freegsnke import interactive_run

REPO = Path(__file__).resolve().parents[1]


def test_interactive_run_prompts_shot_only(monkeypatch) -> None:
    prompts: list[str] = []

    def fake_input(msg: str) -> str:
        prompts.append(msg)
        return "30201"

    captured: dict = {}

    def fake_cli_main(args):
        captured["args"] = list(args)
        return 0

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(interactive_run.cli, "main", fake_cli_main)

    rc = interactive_run.main(["--default-config", str(REPO / "configs" / "default.json")])
    assert rc == 0
    # Exactly one prompt, and it asks for the shot number.
    assert len(prompts) == 1
    assert "shot" in prompts[0].lower()
    # Delegates to the CLI run command with config + shot only.
    assert captured["args"][0] == "run"
    assert "--shot" in captured["args"]
    assert captured["args"][captured["args"].index("--shot") + 1] == "30201"
    assert "--machine" not in captured["args"]


def test_interactive_run_rejects_unknown_args() -> None:
    with pytest.raises(SystemExit) as ei:
        interactive_run.main(["--default-machine-authority", "machine_authority"])
    assert ei.value.code == 2


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
