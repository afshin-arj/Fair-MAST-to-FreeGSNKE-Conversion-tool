"""Regression: Windows reader locks must not abort atomic JSON writes."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, List
from unittest import mock

import pytest

from mast_freegsnke.util import write_json


def test_write_json_retries_replace_then_succeeds(tmp_path: Path) -> None:
    path = tmp_path / "progress.json"
    write_json(path, {"n": 0})

    calls: List[Any] = []
    real_replace = os.replace

    def flaky_replace(src: Any, dst: Any) -> None:
        calls.append((src, dst))
        if len(calls) < 3:
            err = PermissionError(5, "Access is denied")
            err.winerror = 5  # type: ignore[attr-defined]
            raise err
        real_replace(src, dst)

    with mock.patch("mast_freegsnke.util.os.replace", side_effect=flaky_replace):
        with mock.patch("mast_freegsnke.util.time.sleep"):
            write_json(path, {"n": 1, "ok": True})

    assert len(calls) == 3
    obj = json.loads(path.read_text(encoding="utf-8"))
    assert obj == {"n": 1, "ok": True}
    assert not list(tmp_path.glob("*.tmp"))


def test_write_json_falls_back_to_direct_write_after_retries(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    write_json(path, {"v": 1})

    def always_locked(src: Any, dst: Any) -> None:
        err = OSError(13, "Access is denied")
        err.winerror = 5  # type: ignore[attr-defined]
        raise err

    with mock.patch("mast_freegsnke.util.os.replace", side_effect=always_locked):
        with mock.patch("mast_freegsnke.util.time.sleep"):
            write_json(path, {"v": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 2}
    assert not list(tmp_path.glob("*.tmp"))


def test_write_json_non_lock_errors_raise_immediately(tmp_path: Path) -> None:
    path = tmp_path / "x.json"

    def boom(src: Any, dst: Any) -> None:
        raise FileNotFoundError("missing dest parent weirdness")

    with mock.patch("mast_freegsnke.util.os.replace", side_effect=boom):
        with pytest.raises(FileNotFoundError):
            write_json(path, {"a": 1})
