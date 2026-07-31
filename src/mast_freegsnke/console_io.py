"""Console output helpers for Windows cp1252 / limited consoles."""

from __future__ import annotations

import sys
from typing import Any, TextIO


def console_print(*args: Any, sep: str = " ", end: str = "\n", file: TextIO | None = None, flush: bool = False) -> None:
    """print() that never raises UnicodeEncodeError on narrow consoles."""
    stream = file if file is not None else sys.stdout
    text = sep.join(str(a) for a in args) + end
    try:
        stream.write(text)
    except UnicodeEncodeError:
        enc = getattr(stream, "encoding", None) or "ascii"
        stream.write(text.encode(enc, errors="replace").decode(enc, errors="replace"))
    if flush:
        try:
            stream.flush()
        except Exception:
            pass
