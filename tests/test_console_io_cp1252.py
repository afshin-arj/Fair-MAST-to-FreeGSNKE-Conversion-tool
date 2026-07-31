"""Windows console: advisories must not crash cp1252 print."""

from __future__ import annotations

import io

from mast_freegsnke.console_io import console_print
from mast_freegsnke.shot_suitability import _GIF_EXPECTATION_ADVISORIES


def test_gif_expectation_advisories_are_cp1252_safe() -> None:
    for line in _GIF_EXPECTATION_ADVISORIES:
        line.encode("cp1252")  # raises if ≠ / ρ / → slip back in


def test_console_print_survives_narrow_encoding() -> None:
    buf = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    # Force a write path that would fail with raw print of ≠
    console_print("ok != bad", file=buf, flush=True)
    console_print("has ≠ symbol", file=buf, flush=True)
    buf.seek(0)
    raw = buf.buffer.getvalue()
    assert b"ok" in raw
