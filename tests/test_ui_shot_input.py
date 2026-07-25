"""Shot control input parsing / library UX helpers."""
from __future__ import annotations

from pathlib import Path

from mast_freegsnke_ui.app import _parse_shot_number, _shot_library_options


def test_parse_shot_number() -> None:
    assert _parse_shot_number(None) is None
    assert _parse_shot_number("") is None
    assert _parse_shot_number("  ") is None
    assert _parse_shot_number("30201") == 30201
    assert _parse_shot_number(" 30201 ") == 30201
    assert _parse_shot_number(30201) == 30201
    assert _parse_shot_number("0") is None
    assert _parse_shot_number("-3") is None
    assert _parse_shot_number("abc") is None


def test_library_options_label_starts_with_shot(tmp_path: Path) -> None:
    shot = tmp_path / "30299"
    shot.mkdir()
    (shot / "manifest.json").write_text('{"shot": 30299, "status": "success", "blocking_errors": []}\n')
    (shot / "01_summary").mkdir()
    (shot / "01_summary" / "SUMMARY.json").write_text(
        '{"shot": 30299, "status": "success", "blocking_errors": []}\n'
    )
    opts = _shot_library_options(tmp_path)
    assert opts
    assert opts[0]["value"] == 30299
    assert str(opts[0]["label"]).startswith("30299")
