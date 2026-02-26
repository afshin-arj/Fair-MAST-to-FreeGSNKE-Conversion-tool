"""
Forensic comparator between two run/pack directories (v8.0.0).

Detects:
- missing/extra files (based on declared hash maps)
- hash mismatches
- first differing artifact (deterministic path ordering)
- divergence attribution class (DATA/CONTRACT/CODE/ENV/AUDIT)

© 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json

from ..util import write_json
from ..replay.replayer import _load_hash_map, _categorize
from .schema import ForensicDelta


def _divergence_class(path: Optional[str]) -> str:
    if path is None:
        return "NONE"
    cat = _categorize(path)
    if cat == "CONTRACTS":
        return "CONTRACT"
    if cat == "CODE_ENV_PROVENANCE":
        return "CODE_ENV"
    if cat == "MACHINE_AUTHORITY":
        return "DATA_AUTHORITY"
    if cat == "AUDITS": 
        return "AUDIT_LAYER"
    return "DATA_OUTPUT"


def forensic_compare(A: Path, B: Path, out_dir: Optional[Path] = None) -> ForensicDelta:
    A = Path(A)
    B = Path(B)

    mA, _ = _load_hash_map(A)
    mB, _ = _load_hash_map(B)

    keysA = set(mA.keys())
    keysB = set(mB.keys())
    common = sorted(keysA & keysB)

    onlyA = sorted(keysA - keysB)
    onlyB = sorted(keysB - keysA)

    mismatches: List[Dict[str, Any]] = []
    first_diff = None

    for k in common:
        if mA[k] != mB[k]:
            mismatches.append({"path": k, "sha256_A": mA[k], "sha256_B": mB[k], "category": _categorize(k)})
            if first_diff is None:
                first_diff = mismatches[-1]

    ok = (len(onlyA) == 0 and len(onlyB) == 0 and len(mismatches) == 0)
    div = _divergence_class(first_diff["path"] if first_diff else (onlyA[0] if onlyA else (onlyB[0] if onlyB else None)))

    delta = ForensicDelta(
        schema_version="v8.0.0",
        A=str(A),
        B=str(B),
        ok=ok,
        n_files_A=int(len(mA)),
        n_files_B=int(len(mB)),
        n_common=int(len(common)),
        n_only_A=int(len(onlyA)),
        n_only_B=int(len(onlyB)),
        n_mismatch=int(len(mismatches)),
        first_difference=first_diff,
        divergence_class=div,
        mismatches=mismatches[:200],  # cap for report size
    )

    if out_dir is None:
        out_dir = Path.cwd() / "forensics"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "FORENSIC_DELTA.json", delta.to_dict())

    md = []
    md.append("# FORENSIC DELTA\n\n")
    md.append(f"A: `{delta.A}`\n\n")
    md.append(f"B: `{delta.B}`\n\n")
    md.append(f"OK: **{delta.ok}**\n\n")
    md.append(f"Common: {delta.n_common}  OnlyA: {delta.n_only_A}  OnlyB: {delta.n_only_B}  Mismatch: {delta.n_mismatch}\n\n")
    md.append(f"Divergence class: **{delta.divergence_class}**\n\n")
    if delta.first_difference is not None:
        fd = delta.first_difference
        md.append("## First difference\n\n")
        md.append(f"- path: `{fd['path']}`\n")
        md.append(f"- category: `{fd['category']}`\n\n")
    (out_dir / "FORENSIC_DELTA.md").write_text("".join(md), encoding="utf-8")

    return delta
