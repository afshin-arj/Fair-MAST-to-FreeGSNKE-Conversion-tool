"""Shared multi-shot batch loop for the CLI and the interactive launcher.

One implementation of per-shot headers, batch summary, worst-exit-code
semantics, optional abort-on-first-failure, and suitability skip-to-next
so CLI --shots and the interactive prompt cannot drift apart.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

from .shot_suitability import EXIT_UNSUITABLE, ShotSuitability, format_unsuitable_message


def run_shot_batch(
    shots: List[int],
    run_one: Callable[[int], int],
    runs_dir: Path,
    abort_on_failure: bool = False,
    describe: Optional[Callable[[int], str]] = None,
    suitability: Optional[Callable[[int], Union[ShotSuitability, bool]]] = None,
) -> int:
    """Run shots sequentially; return the worst (max) exit code among executed shots.

    When ``suitability`` is provided and a shot is unsuitable, print a
    professional message, skip the pipeline for that shot, and continue to the
    next (does not trigger abort_on_failure).

    When abort_on_failure is True the batch stops at the first *executed*
    failing shot and the remaining shots are reported as skipped.
    """
    runs_dir = Path(runs_dir)
    results: List[Tuple[int, int]] = []
    skipped_abort: List[int] = []
    skipped_unsuitable: List[int] = []

    def _is_suitable(shot: int) -> Tuple[bool, Optional[ShotSuitability]]:
        if suitability is None:
            return True, None
        raw = suitability(shot)
        if isinstance(raw, ShotSuitability):
            return bool(raw.suitable), raw
        return bool(raw), None

    for i, shot in enumerate(shots, start=1):
        print("")
        print("=" * 75)
        print(f"[INFO] ({i}/{len(shots)}) Shot {shot}")
        print(f"[INFO] Output folder: {runs_dir / str(shot)}")
        if describe is not None:
            print(f"[INFO] Running: {describe(shot)}")
        print("=" * 75)
        print("")

        ok, rep = _is_suitable(shot)
        if not ok:
            if rep is not None:
                print(format_unsuitable_message(rep))
            else:
                print(
                    f"[SKIP] Shot {shot} is not suitable for analysis — "
                    "continuing with the next shot."
                )
            if i < len(shots):
                print(f"[INFO] Moving to the next shot ({shots[i]}).")
            else:
                print("[INFO] No further shots in this queue.")
            skipped_unsuitable.append(shot)
            results.append((shot, EXIT_UNSUITABLE))
            continue

        rc = run_one(shot)
        results.append((shot, rc))
        if rc != 0:
            print(f"[FAIL] Shot {shot} exited with code {rc}")
            if abort_on_failure:
                skipped_abort = list(shots[i:])
                if skipped_abort:
                    print(
                        "[WARN] batch_abort_on_failure=true: skipping remaining shots: "
                        + ", ".join(str(s) for s in skipped_abort)
                    )
                break
        else:
            print(f"[OK] Shot {shot} completed → {runs_dir / str(shot)}")

    executed = [(s, rc) for s, rc in results if rc != EXIT_UNSUITABLE]
    if executed:
        worst_rc = max(rc for _, rc in executed)
    elif skipped_unsuitable and not executed:
        worst_rc = EXIT_UNSUITABLE
    else:
        worst_rc = 0

    if len(shots) > 1 or skipped_unsuitable:
        print("")
        print("=" * 75)
        print("[INFO] Batch summary")
        print("=" * 75)
        for shot, rc in results:
            if rc == EXIT_UNSUITABLE:
                print(f"  [SKIP] shot {shot}  (not suitable for analysis)")
            else:
                mark = "OK  " if rc == 0 else "FAIL"
                print(f"  [{mark}] shot {shot}  (exit {rc})  → {runs_dir / str(shot)}")
        for shot in skipped_abort:
            print(f"  [SKIP] shot {shot}  (not run: batch_abort_on_failure)")
        failed = [shot for shot, rc in results if rc not in (0, EXIT_UNSUITABLE)]
        if not failed and not skipped_abort and not skipped_unsuitable:
            print(f"[OK] All {len(shots)} shots completed successfully.")
        elif not failed and skipped_unsuitable and executed and all(rc == 0 for _, rc in executed):
            print(
                f"[OK] {len(executed)} suitable shot(s) completed; "
                f"{len(skipped_unsuitable)} unsuitable skipped: "
                + ", ".join(str(s) for s in skipped_unsuitable)
            )
        else:
            parts = []
            if failed:
                parts.append(
                    f"{len(failed)}/{len(shots)} shots failed: "
                    + ", ".join(str(s) for s in failed)
                )
            if skipped_unsuitable:
                parts.append(
                    "unsuitable: " + ", ".join(str(s) for s in skipped_unsuitable)
                )
            if skipped_abort:
                parts.append(
                    "skipped(abort): " + ", ".join(str(s) for s in skipped_abort)
                )
            print("[FAIL] " + "; ".join(parts) if failed or skipped_abort else "[INFO] " + "; ".join(parts))
    return worst_rc
