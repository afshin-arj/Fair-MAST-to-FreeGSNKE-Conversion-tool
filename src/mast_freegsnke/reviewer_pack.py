from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .util import ensure_dir


DEFAULT_ITEMS = [
    "manifest.json",
    "00_START_HERE.txt",
    "01_summary",
    "02_measured_data",
    "04_efit_compare",
    "probe_geometry_report.json",
    "magnetic_probes.pickle",
    "magnetic_probes.json",
    "06_authorities/machine_authority_snapshot",
    "machine_authority_snapshot",
    "06_authorities/contracts",
    "contracts",
    "03_reconstruction/synthetic",
    "synthetic",
    "03_reconstruction/metrics",
    "metrics",
    "logs",
    "report",
    "06_authorities/provenance/manifest_v2.json",
    "provenance/manifest_v2.json",
    "06_authorities/provenance/file_hashes.json",
    "provenance/file_hashes.json",
    "06_authorities/provenance/env_fingerprint.json",
    "provenance/env_fingerprint.json",
    "06_authorities/provenance/requirements.freeze.json",
    "provenance/requirements.freeze.json",
    "06_authorities/provenance/repo_state.json",
    "provenance/repo_state.json",
]


def build_reviewer_pack(run_dir: Path, out_dir: Optional[Path] = None, items: Optional[List[str]] = None) -> Dict[str, object]:
    run_dir = Path(run_dir)
    if out_dir is None:
        out_dir = run_dir / "REVIEWER_PACK"
    out_dir = ensure_dir(out_dir)
    items = items or list(DEFAULT_ITEMS)

    copied: List[str] = []
    missing: List[str] = []
    seen_dst: set[str] = set()

    for item in items:
        src = run_dir / item
        if not src.exists():
            missing.append(item)
            continue
        # Prefer numbered layout names in the pack when both legacy+new exist
        dst_name = item
        if item.startswith("03_reconstruction/"):
            dst_name = item.split("/", 1)[-1]
        elif item.startswith("06_authorities/"):
            dst_name = item.split("/", 1)[-1]
        if dst_name in seen_dst:
            continue
        dst = out_dir / dst_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        copied.append(item)
        seen_dst.add(dst_name)

    # Minimal README for reviewer pack
    readme = out_dir / "README.md"
    readme.write_text(
        """# REVIEWER PACK

This folder is a self-contained export of a single MAST -> FreeGSNKE reconstruction run.

## Contents
- `manifest.json`: pipeline manifest (v1 schema, human-readable)
- `01_summary/`: science residuals + SUMMARY
- `04_efit_compare/`: FAIR-MAST EFIT++ archive compare (ADR-002) when enabled
- `provenance/manifest_v2.json`: reproducibility manifest (v2 schema, hash-based)
- `machine_authority_snapshot/`: frozen machine authority used for this run
- `contracts/`: resolved diagnostic contracts and coil maps
- `synthetic/`, `metrics/`, `report/`: normalized synthetic traces, residual tables, and plots (if generated)
- `logs/`: FreeGSNKE execution stdout/stderr (if execution enabled)

## Replay guidance
Re-run the pipeline using the same repository revision, machine authority, and configuration.
Use `provenance/file_hashes.json` to verify that deterministic inputs/outputs match.
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return {"ok": True, "out_dir": str(out_dir), "copied": copied, "missing": missing}
