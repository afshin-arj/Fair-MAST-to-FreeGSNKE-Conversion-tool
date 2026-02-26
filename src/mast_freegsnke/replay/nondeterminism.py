"""
Non-determinism sentinel (v8.0.0).

Computes a deterministic hash of the target's declared hash map N times and asserts stability.
This catches ordering/serialization issues in the replay layer (and in any fallback hashing).

© 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

from pathlib import Path
from typing import List
import json
import hashlib

from .replayer import _load_hash_map
from .schema import NondeterminismReport
from ..util import write_json


def _stable_digest(mapping: dict) -> str:
    txt = json.dumps(mapping, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()


def nondeterminism_check(target: Path, n: int = 3, out_dir: Path | None = None) -> NondeterminismReport:
    target = Path(target)
    n = int(n)
    if n < 2:
        raise ValueError("n must be >= 2")
    hashes: List[str] = []
    for _ in range(n):
        m, _ = _load_hash_map(target)
        hashes.append(_stable_digest(m))

    ok = (len(set(hashes)) == 1)
    note = "stable" if ok else "hash-map digest differed across replays (suspected nondeterminism)"

    rep = NondeterminismReport(schema_version="v8.0.0", target=str(target), n=n, ok=ok, run_hashes=hashes, note=note)

    if out_dir is None:
        out_dir = target / "replay"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "NONDETERMINISM_REPORT.json", rep.to_dict())
    return rep
