"""Shared process exit codes for the shot-only CLI, batch loop, and UI.

Kept in one module so the CLI, the interactive launcher (batch loop), and the
tests agree on semantics:

- ``0``    run completed, status ``success``
- ``11``   run failed (``blocking_errors`` present or status ``failed``)
- ``17``   run completed but ``degraded`` (``degraded_notes`` only) — the pack
           is usable; honesty flags are recorded in ``manifest.json``.
           Degraded must be distinguishable from failure for automation, while
           still being a non-zero signal.
- ``20``   shot unsuitable (``shot_suitability.EXIT_UNSUITABLE``)

Historical codes already claimed elsewhere: 12 (manifest unreadable), 15
(certify failed), 16 (replay failed), 30-35 / 40-46 (analysis subcommands).
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

EXIT_FAILED = 11
EXIT_DEGRADED = 17


def run_exit_for_manifest(manifest: Mapping[str, Any] | Dict[str, Any] | None) -> int:
    """Map a run ``manifest.json`` payload to a process exit code.

    Returns ``0`` (success), ``EXIT_DEGRADED`` (17), or ``EXIT_FAILED`` (11).
    Fails closed on missing/unknown status.
    """
    man = dict(manifest or {})
    status = str(man.get("status") or "")
    if man.get("blocking_errors") or status == "failed":
        return EXIT_FAILED
    if status == "degraded":
        return EXIT_DEGRADED
    if status == "success":
        return 0
    return EXIT_FAILED
