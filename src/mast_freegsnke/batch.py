"""Shared multi-shot batch loop for the CLI and the interactive launcher.

One implementation of per-shot headers, batch summary, worst-exit-code
semantics, and optional abort-on-first-failure so CLI --shots and the
interactive prompt cannot drift apart.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Tuple


def run_shot_batch(
    shots: List[int],
    run_one: Callable[[int], int],
    runs_dir: Path,
    abort_on_failure: bool = False,
    describe: Optional[Callable[[int], str]] = None,
) -> int:
    """Run shots sequentially; return the worst (max) exit code.

    When abort_on_failure is True the batch stops at the first failing shot and
    the remaining shots are reported as skipped in the summary.
    """
    runs_dir = Path(runs_dir)
    results: List[Tuple[int, int]] = []
    skipped: List[int] = []

    for i, shot in enumerate(shots, start=1):
        print("")
        print("=" * 75)
        print(f"[INFO] ({i}/{len(shots)}) Running shot {shot}")
        print(f"[INFO] Output folder: {runs_dir / str(shot)}")
        if describe is not None:
            print(f"[INFO] Running: {describe(shot)}")
        print("=" * 75)
        print("")
        rc = run_one(shot)
        results.append((shot, rc))
        if rc != 0:
            print(f"[FAIL] Shot {shot} exited with code {rc}")
            if abort_on_failure:
                skipped = list(shots[i:])
                if skipped:
                    print(
                        "[WARN] batch_abort_on_failure=true: skipping remaining shots: "
                        + ", ".join(str(s) for s in skipped)
                    )
                break
        else:
            print(f"[OK] Shot {shot} completed → {runs_dir / str(shot)}")

    worst_rc = max((rc for _, rc in results), default=0)
    if len(shots) > 1:
        print("")
        print("=" * 75)
        print("[INFO] Batch summary")
        print("=" * 75)
        for shot, rc in results:
            mark = "OK  " if rc == 0 else "FAIL"
            print(f"  [{mark}] shot {shot}  (exit {rc})  → {runs_dir / str(shot)}")
        for shot in skipped:
            print(f"  [SKIP] shot {shot}  (not run: batch_abort_on_failure)")
        failed = [shot for shot, rc in results if rc != 0]
        if not failed and not skipped:
            print(f"[OK] All {len(shots)} shots completed successfully.")
        else:
            print(
                f"[FAIL] {len(failed)}/{len(shots)} shots failed: "
                + ", ".join(str(s) for s in failed)
                + (f" (skipped: {', '.join(str(s) for s in skipped)})" if skipped else "")
            )
    return worst_rc
