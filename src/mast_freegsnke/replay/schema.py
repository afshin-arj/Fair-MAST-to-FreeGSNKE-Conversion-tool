from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
import json
import hashlib

def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def sha256_text(txt: str) -> str:
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()

@dataclass(frozen=True)
class ReplayCheck:
    path: str
    expected_sha256: Optional[str]
    actual_sha256: Optional[str]
    ok: bool
    category: str
    note: str = ""

@dataclass(frozen=True)
class ReplayReport:
    schema_version: str
    target: str
    mode: str  # strict|relaxed
    ok: bool
    n_files: int
    n_mismatch: int
    n_missing: int
    env_match: Optional[bool]
    env_diff: Optional[Dict[str, Any]]
    checks: List[ReplayCheck]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "target": self.target,
            "mode": self.mode,
            "ok": self.ok,
            "n_files": self.n_files,
            "n_mismatch": self.n_mismatch,
            "n_missing": self.n_missing,
            "env_match": self.env_match,
            "env_diff": self.env_diff,
            "checks": [asdict(c) for c in self.checks],
        }

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def hash(self) -> str:
        return sha256_text(self.to_canonical_json())

@dataclass(frozen=True)
class NondeterminismReport:
    schema_version: str
    target: str
    n: int
    ok: bool
    run_hashes: List[str]
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
