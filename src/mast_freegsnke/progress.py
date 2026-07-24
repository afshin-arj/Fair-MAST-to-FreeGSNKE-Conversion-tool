"""Live run progress sidecar for UI / external watchers.

Writes ``SHOT/<N>/progress.json`` after each pipeline stage so a Dash (or other)
client can poll without waiting for the final ``manifest.json``.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .util import write_json


def write_run_progress(
    run_dir: Path,
    *,
    shot: int,
    status: str,
    stage_log: List[Dict[str, Any]],
    blocking_errors: Optional[List[str]] = None,
    current_stage: Optional[str] = None,
) -> Path:
    """Flush a compact progress snapshot next to the run directory.

    Parameters
    ----------
    run_dir:
        ``SHOT/<N>`` (or configured runs_dir / shot).
    shot:
        MAST shot number.
    status:
        ``started`` | ``running`` | ``success`` | ``failed`` (or cancelled by UI).
    stage_log:
        Same list appended by the pipeline ``_stage`` helper.
    blocking_errors:
        Current blocking error strings (may be empty).
    current_stage:
        Name of the stage just recorded; defaults to the last stage_log entry.
    """
    run_dir = Path(run_dir)
    if current_stage is None and stage_log:
        last = stage_log[-1]
        if isinstance(last, dict):
            current_stage = str(last.get("stage") or last.get("name") or "") or None
    payload: Dict[str, Any] = {
        "shot": int(shot),
        "status": str(status),
        "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "current_stage": current_stage,
        "stage_log": list(stage_log),
        "blocking_errors": list(blocking_errors or []),
    }
    out = run_dir / "progress.json"
    write_json(out, payload)
    return out
