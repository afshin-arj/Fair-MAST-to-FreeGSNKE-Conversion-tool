#!/usr/bin/env python3
"""DEPRECATED: fetch FreeGSNKE public MAST-U-like pickles (archive only).

FAIR-MAST publishes classic MAST data. Production ``machine_authority/`` must use
classic MAST pickles built from Level-2 filaments:

  python scripts/build_classic_mast_machine.py --shot-cache data_cache/shot_30201

This script only downloads MAST-U-like pickles into ``machine_authority/archive_mastu_like/``
for historical reference — it does NOT write production active_coils/limiter paths.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/FusionComputingLab/freegsnke/main/machine_configs/MAST-U"
OUT = Path(__file__).resolve().parents[1] / "machine_authority" / "archive_mastu_like"
MAPPING = {
    "MAST-U_like_active_coils.pickle": "active_coils.pickle",
    "MAST-U_like_passive_coils.pickle": "passive_coils.pickle",
    "MAST-U_like_limiter.pickle": "limiter.pickle",
    "MAST-U_like_wall.pickle": "wall.pickle",
}


def main() -> int:
    print(
        "[WARN] FAIR-MAST = classic MAST. Prefer scripts/build_classic_mast_machine.py "
        "for production machine_authority/. This script archives MAST-U-like pickles only."
    )
    OUT.mkdir(parents=True, exist_ok=True)
    for src, dst in MAPPING.items():
        url = f"{BASE}/{src}"
        target = OUT / dst
        print(f"[INFO] fetch {url}")
        target.write_bytes(urllib.request.urlopen(url, timeout=120).read())
        print(f"[OK] {target} ({target.stat().st_size} bytes)")
    prov = {
        "source": "https://github.com/FusionComputingLab/freegsnke/tree/main/machine_configs/MAST-U",
        "files": list(MAPPING.values()),
        "note": (
            "ARCHIVED FreeGSNKE MAST-U-like structural pickles. "
            "Not used for FAIR-MAST classic MAST production. "
            "Rebuild production machine with scripts/build_classic_mast_machine.py."
        ),
        "status": "archived_not_production",
    }
    (OUT / "FREEGSNKE_MACHINE_PROVENANCE.json").write_text(
        json.dumps(prov, indent=2) + "\n", encoding="utf-8"
    )
    print("[OK] wrote archive provenance under", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
