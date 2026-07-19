from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Optional

from .util import ensure_dir


DEFAULT_ITEMS = [
    "manifest.json",
    "probe_geometry_report.json",
    "magnetic_probes.pickle",
    "magnetic_probes.json",
    "machine_authority_snapshot",
    "contracts",
    "synthetic",
    "metrics",
    "logs",
    "report",
    "provenance/manifest_v2.json",
    "provenance/file_hashes.json",
    "provenance/env_fingerprint.json",
    "provenance/requirements.freeze.json",
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

    for item in items:
        src = run_dir / item
        if not src.exists():
            missing.append(item)
            continue
        dst = out_dir / item
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        copied.append(item)

    # Minimal README for reviewer pack
    readme = out_dir / "README.md"
    readme.write_text(
        """# REVIEWER PACK

This folder is a self-contained export of a single MAST -> FreeGSNKE reconstruction run.

## Contents
- `manifest.json`: pipeline manifest (v1 schema, human-readable)
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
