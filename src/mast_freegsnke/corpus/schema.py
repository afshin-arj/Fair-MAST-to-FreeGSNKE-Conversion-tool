from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import re

from ..util import sha256_file

REQUIRED_ROBUSTNESS_FILES = (
    "per_window_summary.csv",
    "global_robust_choice.json",
    "stability_scorecard.json",
    "phase_consistency_scorecard.json",
    "sensitivity_attribution.json",
    "plots_manifest.json",
)

@dataclass(frozen=True)
class CorpusEntry:
    """A single run directory entry in a corpus.

    The corpus does not re-run physics; it indexes already-produced robustness artifacts (v4+).
    """
    run_dir: str
    shot: Optional[int]
    robustness_dir: str
    hashes: Dict[str, str]

    @staticmethod
    def infer_shot(run_dir: Path) -> Optional[int]:
        # Legacy: runs/shot_30201  ·  Current: SHOTS/30201
        m = re.search(r"shot_(\d+)", str(run_dir))
        if m:
            return int(m.group(1))
        if run_dir.name.isdigit():
            return int(run_dir.name)
        return None

    @classmethod
    def from_run_dir(cls, run_dir: Path, robustness_subdir: str = "robustness_v4") -> "CorpusEntry":
        run_dir = run_dir.resolve()
        rob = run_dir / robustness_subdir
        if not rob.exists():
            raise FileNotFoundError(f"robustness directory not found: {rob}")
        hashes: Dict[str, str] = {}
        for fn in REQUIRED_ROBUSTNESS_FILES:
            p = rob / fn
            if not p.exists():
                raise FileNotFoundError(f"required robustness artifact missing: {p}")
            hashes[fn] = sha256_file(p)
        return cls(
            run_dir=str(run_dir),
            shot=cls.infer_shot(run_dir),
            robustness_dir=str(rob),
            hashes=hashes,
        )

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sha256_text(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def corpus_id(entries: List[CorpusEntry]) -> str:
    """Deterministic corpus id from entries and their file hashes."""
    payload = {
        "entries": [
            {
                "run_dir": e.run_dir,
                "shot": e.shot,
                "robustness_dir": e.robustness_dir,
                "hashes": dict(sorted(e.hashes.items())),
            }
            for e in sorted(entries, key=lambda x: (x.shot if x.shot is not None else 10**12, x.run_dir))
        ]
    }
    return sha256_text(canonical_json(payload))
