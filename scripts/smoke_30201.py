#!/usr/bin/env python3
"""Local smoke for shot 30201 (not committed as required runtime)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mast_freegsnke.cli import main


def main_smoke() -> int:
    s5 = ROOT / "tools" / "s5cmd.exe"
    if not s5.exists():
        print("[FAIL] tools/s5cmd.exe missing")
        return 2
    cfg = json.loads((ROOT / "configs" / "smoke_data_path.json").read_text(encoding="utf-8"))
    cfg["s5cmd_path"] = str(s5.resolve())
    local = ROOT / "configs" / "smoke_data_path.local.json"
    local.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"[INFO] local config -> {local}", flush=True)

    print("=== CHECK 30201 ===", flush=True)
    rc_check = main(["check", "--shot", "30201", "--config", str(local)])
    print(f"check_exit={rc_check}", flush=True)
    if rc_check != 0:
        return rc_check

    print("=== RUN smoke_data_path 30201 ===", flush=True)
    rc_run = main(["run", "--shot", "30201", "--config", str(local)])
    print(f"run_exit={rc_run}", flush=True)
    return rc_run


if __name__ == "__main__":
    raise SystemExit(main_smoke())
