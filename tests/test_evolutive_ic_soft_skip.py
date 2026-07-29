"""Evolutive soft-skip when IC static GS times out after inverse/forward success."""

from mast_freegsnke.freegsnke_runner import evolutive_timeout_is_soft


def test_evolutive_ic_timeout_soft_skip() -> None:
    assert evolutive_timeout_is_soft(
        returncode=124,
        timed_out=False,
        stdout_text="[TIMEOUT] evolutive ic_static_gs step -1 exceeded per_step_timeout_s=180.0",
        n_partial=0,
    )
    assert not evolutive_timeout_is_soft(
        returncode=1,
        timed_out=False,
        stdout_text="[TIMEOUT] evolutive ic_static_gs step -1",
        n_partial=0,
    )
    assert evolutive_timeout_is_soft(
        returncode=124,
        timed_out=False,
        stdout_text="nlstepper hung",
        n_partial=3,
    )
    assert evolutive_timeout_is_soft(
        returncode=0,
        timed_out=True,
        stdout_text="",
        n_partial=2,
    )
