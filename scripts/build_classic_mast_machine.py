#!/usr/bin/env python3
"""Build classic MAST FreeGSNKE machine pickles from a FAIR-MAST shot cache."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mast_freegsnke.classic_mast_machine import write_classic_mast_machine


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Build classic MAST active/limiter/wall pickles from FAIR-MAST Level-2 "
            "(replaces MAST-U-like FreeGSNKE public pickles in machine_authority/)."
        )
    )
    ap.add_argument(
        "--shot-cache",
        default="data_cache/shot_30201",
        help="FAIR-MAST shot cache directory (contains pf_active.zarr + wall.zarr)",
    )
    ap.add_argument("--out", default="machine_authority", help="Output machine directory")
    ap.add_argument("--shot", type=int, default=None, help="Shot number for provenance")
    ap.add_argument(
        "--no-archive",
        action="store_true",
        help="Do not move existing MAST-U-like pickles to archive_mastu_like/",
    )
    ap.add_argument(
        "--validate-tokamak",
        action="store_true",
        help="Load result with freegsnke.build_machine.tokamak (needs freegsnke installed)",
    )
    ns = ap.parse_args()
    shot = ns.shot
    if shot is None:
        name = Path(ns.shot_cache).name
        if name.startswith("shot_"):
            try:
                shot = int(name.split("_", 1)[1])
            except ValueError:
                shot = None
    rep = write_classic_mast_machine(
        Path(ns.shot_cache),
        Path(ns.out),
        shot=shot,
        archive_mastu=not ns.no_archive,
        validate_tokamak=bool(ns.validate_tokamak),
    )
    print(json.dumps(rep, indent=2, sort_keys=True))
    ok = bool(rep.get("ok"))
    tv = rep.get("tokamak_validation")
    if isinstance(tv, dict) and tv.get("skipped") is not True and not tv.get("ok"):
        ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
