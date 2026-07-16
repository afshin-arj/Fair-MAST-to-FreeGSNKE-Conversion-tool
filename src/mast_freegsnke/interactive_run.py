"""Interactive launcher: shot number only; all other knobs from config.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Optional

from . import cli
from .config import AppConfig


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
    print(f"[INFO] execute_freegsnke={cfg.execute_freegsnke} mode={cfg.freegsnke_run_mode}")
    print(f"[INFO] machine_authority_dir={cfg.machine_authority_dir}")
    print(f"[INFO] coil_map_path={cfg.coil_map_path}")
    print(f"[INFO] enable_contract_metrics={cfg.enable_contract_metrics}")
    print("")

    shot = _prompt_required_int("Enter MAST shot number (required, digits; 'q' to quit): ")

    args = ["run", "--config", str(config_path), "--shot", str(shot)]
    # --machine omitted: CLI resolves from config.machine_authority_dir

    print("")
    print("[INFO] Running: mast-freegsnke " + " ".join(args))
    print("")
    return cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
