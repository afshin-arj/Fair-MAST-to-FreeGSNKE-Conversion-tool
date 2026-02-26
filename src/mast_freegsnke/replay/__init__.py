"""
Truth-by-Replay Authority (v8.0.0)
Deterministic artifact replay/verification and non-determinism sentinels.
© 2026 Afshin Arjhangmehr
"""

from .replayer import replay_run, ReplayReport
from .nondeterminism import nondeterminism_check, NondeterminismReport

__all__ = ["replay_run", "ReplayReport", "nondeterminism_check", "NondeterminismReport"]
