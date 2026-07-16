#!/usr/bin/env python3
"""Build machine_authority/ from a FAIR-MAST shot cache (no invented metrology)."""
from __future__ import annotations

import argparse
from pathlib import Path

from mast_freegsnke.fairmast_authority import write_machine_authority_from_shot_cache


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot-cache", required=True, help="e.g. data_cache/shot_30201")
    ap.add_argument("--out", default="machine_authority", help="Output authority directory")
    ap.add_argument("--shot", type=int, default=None)
    ns = ap.parse_args()
    rep = write_machine_authority_from_shot_cache(Path(ns.shot_cache), Path(ns.out), shot=ns.shot)
    print(rep)
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
