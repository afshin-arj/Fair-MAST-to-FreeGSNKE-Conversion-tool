"""Expert-facing SHOT/<N>/ folder layout (numbered dirs).

Operational FreeGSNKE scripts still expect ``inputs/``, ``*.py``, and dumps at the
run root. This module relocates *human* artifacts into numbered folders and
leaves thin compatibility redirects (``experimental_data`` → ``02_measured_data``,
etc.) via junction on Windows or symlink elsewhere when possible; otherwise a
README pointer file.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# (legacy_or_source, destination under run_dir)
_MOVE_MAP: Tuple[Tuple[str, str], ...] = (
    ("experimental_data", "02_measured_data"),
    ("metrics", "03_reconstruction/metrics"),
    ("synthetic", "03_reconstruction/synthetic"),
    ("presentation", "03_reconstruction/presentation"),
    ("evolutive", "03_reconstruction/evolutive"),
    ("downstream", "05_downstream"),
    ("contracts", "06_authorities/contracts"),
    ("provenance", "06_authorities/provenance"),
    ("machine_authority_snapshot", "06_authorities/machine_authority_snapshot"),
)

_DUMPS: Tuple[str, ...] = ()
# Keep solver dumps and probe pickles at run root — FreeGSNKE scripts and
# evolutive IC loading expect inverse_dump.pkl next to the runners.


def resolve_run_path(run_dir: Path, *candidates: str) -> Optional[Path]:
    """Return first existing path among candidates (new layout then legacy)."""
    run_dir = Path(run_dir)
    for rel in candidates:
        p = run_dir / rel
        if p.exists():
            return p
    return None


def metrics_dir(run_dir: Path) -> Path:
    p = resolve_run_path(run_dir, "03_reconstruction/metrics", "metrics")
    return p if p is not None else Path(run_dir) / "03_reconstruction" / "metrics"


def synthetic_dir(run_dir: Path) -> Path:
    p = resolve_run_path(run_dir, "03_reconstruction/synthetic", "synthetic")
    return p if p is not None else Path(run_dir) / "03_reconstruction" / "synthetic"


def presentation_dir(run_dir: Path) -> Path:
    p = resolve_run_path(run_dir, "03_reconstruction/presentation", "presentation")
    return p if p is not None else Path(run_dir) / "03_reconstruction" / "presentation"


def evolutive_dir(run_dir: Path) -> Path:
    p = resolve_run_path(run_dir, "03_reconstruction/evolutive", "evolutive")
    return p if p is not None else Path(run_dir) / "03_reconstruction" / "evolutive"


def measured_data_dir(run_dir: Path) -> Path:
    p = resolve_run_path(run_dir, "02_measured_data", "experimental_data")
    return p if p is not None else Path(run_dir) / "02_measured_data"


def _try_link(src: Path, dst: Path) -> bool:
    """Create dst -> src directory link (junction on Windows, symlink else)."""
    if dst.exists():
        return False
    try:
        if os.name == "nt":
            # Directory junction (no admin required)
            subprocess_cmd = ["cmd", "/c", "mklink", "/J", str(dst), str(src)]
            import subprocess

            r = subprocess.run(subprocess_cmd, capture_output=True, text=True)
            return r.returncode == 0 and dst.exists()
        os.symlink(src, dst, target_is_directory=True)
        return dst.exists()
    except Exception:
        return False


def _write_pointer(legacy: Path, target_rel: str) -> None:
    legacy.mkdir(parents=True, exist_ok=True)
    (legacy / "MOVED.txt").write_text(
        f"This folder moved to `{target_rel}/` for expert clarity.\n"
        f"Open that path instead. Compatibility shim only.\n",
        encoding="utf-8",
    )


def finalize_shot_layout(run_dir: Path, *, shot: int) -> Dict[str, Any]:
    """Move human-facing artifacts into numbered folders; keep scripts/inputs at root."""
    run_dir = Path(run_dir)
    moves: List[Dict[str, str]] = []
    warnings: List[str] = []

    (run_dir / "03_reconstruction").mkdir(parents=True, exist_ok=True)
    (run_dir / "06_authorities").mkdir(parents=True, exist_ok=True)
    recon = run_dir / "03_reconstruction"

    for src_name, dst_rel in _MOVE_MAP:
        src = run_dir / src_name
        dst = run_dir / dst_rel
        if not src.exists():
            continue
        if src.resolve() == dst.resolve():
            continue
        if dst.exists():
            warnings.append(f"skip_move_dst_exists:{src_name}->{dst_rel}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moves.append({"from": src_name, "to": dst_rel})
        # Compatibility redirect
        if not _try_link(dst, src):
            _write_pointer(src, dst_rel)

    # Solver dumps / probe pickles stay at run root (FreeGSNKE IC paths).

    index = {
        "shot": int(shot),
        "layout_version": "11.9.0",
        "start_here": "00_START_HERE.txt",
        "folders": {
            "01_summary": "Science residuals, SUMMARY, audit JSON",
            "02_measured_data": "FAIR-MAST experimental CSVs + plots (was experimental_data/)",
            "03_reconstruction": "FreeGSNKE metrics, synthetic probes, GIFs, evolutive, dumps",
            "04_efit_compare": "FreeGSNKE vs FAIR-MAST EFIT++ archive (ADR-002)",
            "05_downstream": "Optional TORAX GEQDSK export (ADR-001)",
            "06_authorities": "Contracts, provenance hashes, machine authority snapshot",
            "inputs": "Tooling CSVs + authority snapshots (keep at root for FreeGSNKE scripts)",
            "logs": "FreeGSNKE stdout/stderr",
        },
        "moves": moves,
        "warnings": warnings,
    }
    layout_path = run_dir / "01_summary" / "folder_layout.json"
    layout_path.parent.mkdir(parents=True, exist_ok=True)
    layout_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    start = "\n".join(
        [
            f"SHOT {shot} — start here (Fair-MAST → FreeGSNKE)",
            "=" * 52,
            "",
            "Read in this order:",
            "  1) 01_summary/SUMMARY.md          science residuals + Ip match",
            "  2) 04_efit_compare/COMPARE.md      vs FAIR-MAST EFIT++ archive",
            "  3) 03_reconstruction/metrics/     probe residual scores",
            "  4) 02_measured_data/              FAIR-MAST measured signals",
            "  5) 05_downstream/                 optional TORAX geometry",
            "  6) 06_authorities/                cited authorities + hashes",
            "",
            "Tooling (leave alone unless debugging):",
            "  inputs/   mapped CSVs + authority snapshots for FreeGSNKE scripts",
            "  *.py      generated inverse/forward/evolutive runners",
            "  logs/     execution logs",
            "  manifest.json",
            "",
            "See 01_summary/folder_layout.json for move map.",
            "",
        ]
    )
    (run_dir / "00_START_HERE.txt").write_text(start, encoding="utf-8")
    # Keep legacy name pointing to new
    (run_dir / "00_README.txt").write_text(
        start + "\n(Renamed primary entry: 00_START_HERE.txt)\n",
        encoding="utf-8",
    )

    recon_idx = recon / "INDEX.txt"
    recon_idx.write_text(
        "\n".join(
            [
                "03_reconstruction — FreeGSNKE products",
                "-" * 40,
                "metrics/       contract residual scores",
                "synthetic/     synthesised probe traces",
                "presentation/  equilibrium GIFs (annex)",
                "evolutive/     evolutive Ip residual + GIF",
                "*_dump.pkl     solver dumps stay at run root (IC paths)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    return index
