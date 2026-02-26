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
class ForensicDelta:
    schema_version: str
    A: str
    B: str
    ok: bool
    n_files_A: int
    n_files_B: int
    n_common: int
    n_only_A: int
    n_only_B: int
    n_mismatch: int
    first_difference: Optional[Dict[str, Any]]
    divergence_class: str
    mismatches: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())

    def hash(self) -> str:
        return sha256_text(self.to_canonical_json())
