"""Interactive launcher: shot number(s) only; all other knobs from config.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Optional

from . import cli
from .config import AppConfig


_SHOT_TOKEN = re.compile(r"^[0-9]+$")


def parse_shot_list(raw: str) -> List[int]:
    """Parse one or more shot numbers from a single prompt line.

    Accepts space- and/or comma-separated digits, e.g.:
      30201
      30201 30202
      30201,30202
      30201, 30202 30400
    """
    parts = [p for p in re.split(r"[\s,]+", raw.strip()) if p]
    if not parts:
        raise ValueError("empty")
    shots: List[int] = []
    seen: set[int] = set()
    for p in parts:
        if not _SHOT_TOKEN.fullmatch(p):
            raise ValueError(p)
        n = int(p)
        if n not in seen:
            seen.add(n)
            shots.append(n)
    return shots


def _prompt_shot_list(msg: str) -> List[int]:
    while True:
        s = input(msg).strip()
        if s.lower() == "q":
            raise SystemExit(0)
        if not s:
            print("[WARN] Value is required.")
            continue
        try:
            return parse_shot_list(s)
        except ValueError as e:
            bad = str(e)
            if bad == "empty":
                print("[WARN] Value is required.")
            else:
                print(f"[WARN] Invalid token {bad!r}; use digits only (e.g. 30201 30202).")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="mast-freegsnke-interactive")
    ap.add_argument("--default-config", default="configs/default.json")
    ns = ap.parse_args(argv)

    print("")
    print("===========================================================================")
    print("Interactive Run (shot-only)")
    print("===========================================================================")
    print("")

    config_path = Path(ns.default_config)
    if not config_path.exists():
        print(f"[FAIL] Config file not found: {config_path}")
        print("[HINT] Use configs/default.json (shipped) or pass --default-config <path>.")
        return 2

    cfg = AppConfig.load(config_path)
    print(f"[INFO] Using config: {config_path}")
    print(f"[INFO] runs_dir={cfg.runs_dir}  (outputs → {cfg.runs_dir}/<shot>)")
    print(f"[INFO] execute_freegsnke={cfg.execute_freegsnke} mode={cfg.freegsnke_run_mode}")
    print(f"[INFO] machine_authority_dir={cfg.machine_authority_dir}")
    print(f"[INFO] coil_map_path={cfg.coil_map_path}")
    print(f"[INFO] enable_contract_metrics={cfg.enable_contract_metrics}")
    print("")

    shots = _prompt_shot_list(
        "Enter MAST shot number(s) (digits; space/comma separated; 'q' to quit): "
    )
    print(f"[INFO] Shots queued: {', '.join(str(s) for s in shots)}")

    results: List[tuple[int, int]] = []  # (shot, exit_code)
    for i, shot in enumerate(shots, start=1):
        args = ["run", "--config", str(config_path), "--shot", str(shot)]
        print("")
        print("=" * 75)
        print(f"[INFO] ({i}/{len(shots)}) Running shot {shot}")
        print(f"[INFO] Output folder: {cfg.runs_dir / str(shot)}")
        print("[INFO] Running: mast-freegsnke " + " ".join(args))
        print("=" * 75)
        print("")
        rc = cli.main(args)
        results.append((shot, rc))
        if rc != 0:
            print(f"[FAIL] Shot {shot} exited with code {rc}")
        else:
            print(f"[OK] Shot {shot} completed → {cfg.runs_dir / str(shot)}")

    worst_rc = max((rc for _, rc in results), default=0)
    if len(shots) > 1:
        print("")
        print("=" * 75)
        print("[INFO] Batch summary")
        print("=" * 75)
        for shot, rc in results:
            mark = "OK  " if rc == 0 else "FAIL"
            print(f"  [{mark}] shot {shot}  (exit {rc})  → {cfg.runs_dir / str(shot)}")
        failed = [shot for shot, rc in results if rc != 0]
        if not failed:
            print(f"[OK] All {len(shots)} shots completed successfully.")
        else:
            print(f"[FAIL] {len(failed)}/{len(shots)} shots failed: {', '.join(str(s) for s in failed)}")
    return worst_rc


if __name__ == "__main__":
    raise SystemExit(main())
