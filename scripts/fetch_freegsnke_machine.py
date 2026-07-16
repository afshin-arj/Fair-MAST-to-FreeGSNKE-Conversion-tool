#!/usr/bin/env python3
"""Fetch public FreeGSNKE MAST-U-like structural machine pickles into machine_authority/."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/FusionComputingLab/freegsnke/main/machine_configs/MAST-U"
OUT = Path(__file__).resolve().parents[1] / "machine_authority"
MAPPING = {
    "MAST-U_like_active_coils.pickle": "active_coils.pickle",
    "MAST-U_like_passive_coils.pickle": "passive_coils.pickle",
    "MAST-U_like_limiter.pickle": "limiter.pickle",
    "MAST-U_like_wall.pickle": "wall.pickle",
}


def main() -> int:
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
            "Public FreeGSNKE MAST-U-like structural machine pickles. "
            "Probe metrology is from FAIR-MAST Level-2 (probe_geometry.json / run magnetic_probes.pickle). "
            "Classic MAST shots may need a true MAST coil set when an authoritative public source is available."
        ),
    }
    (OUT / "FREEGSNKE_MACHINE_PROVENANCE.json").write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    print("[OK] wrote FREEGSNKE_MACHINE_PROVENANCE.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
