"""Interactive launcher logic implemented in Python for Windows batch reliability.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import List, Optional

from . import cli


def _prompt(msg: str, default: Optional[str] = None) -> str:
    if default is None:
        return input(msg).strip()
    s = input(f"{msg} [{default}]: ").strip()
    return s or default


def _prompt_required_int(msg: str) -> int:
    while True:
        s = input(msg).strip()
        if s.lower() == "q":
            raise SystemExit(0)
        if not s:
            print("[WARN] Value is required.")
            continue
        if not re.fullmatch(r"[0-9]+", s):
            print("[WARN] Must be digits only (e.g. 30200).")
            continue
        return int(s)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="mast-freegsnke-interactive")
    ap.add_argument("--default-config", default="configs/default.yaml")
    ap.add_argument("--default-machine-authority", default="machine_authority")
    ns = ap.parse_args(argv)

    print("")
    print("===========================================================================")
    print("Interactive Run")
    print("===========================================================================")
    print("")

    config_path = _prompt("Enter config path", default=ns.default_config)
    shot = _prompt_required_int("Enter MAST shot number (required, digits; 'q' to quit): ")

    machine_dir = _prompt("Enter machine authority dir", default=ns.default_machine_authority)
    window_override = input("Optional window override (blank for auto): ").strip()

    # y/n prompts
    def yn(msg: str, default: str = "y") -> str:
        while True:
            s = input(f"{msg} (y/n, default {default}): ").strip().lower()
            if not s:
                s = default
            if s in ("y", "n"):
                return s
            print("[WARN] Please enter y or n.")

    run_freegsnke = yn("Run FreeGSNKE execution now?", default="y")
    run_metrics = yn("Compute contract residual metrics?", default="y")

    args = ["run", "--config", config_path, "--shot", str(shot), "--machine-authority", machine_dir]
    if window_override:
        args += ["--window-override", window_override]
    if run_freegsnke == "n":
        args += ["--skip-freegsnke"]
    if run_metrics == "n":
        args += ["--skip-metrics"]

    print("")
    print("[INFO] Running: mast-freegsnke " + " ".join(args))
    print("")
    return cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
