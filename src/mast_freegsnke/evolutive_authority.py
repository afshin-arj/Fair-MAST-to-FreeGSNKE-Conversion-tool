"""Evolutive (time-dependent) FreeGSNKE execution authority.

Fail-closed: all numerics required for nl_solver / nlstepper must be declared.
Profile shape parameters are NOT declared here — they are held from the inverse
IC / execution_authority profile block (never invented for evolutive).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and (x == x)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


@dataclass(frozen=True)
class EvolutiveAuthority:
    authority_name: str
    authority_version: str
    full_timestep_s: float
    n_steps: int
    linear_only: bool
    plasma_resistivity_ohm_m: float
    max_solving_iterations: int
    max_mode_frequency: float
    script_timeout_s: float
    snapshot_equilibria_every_n: int = 5
    min_dIy_dI: Optional[float] = None
    notes: str = ""

    def validate(self) -> None:
        _require(isinstance(self.authority_name, str) and self.authority_name.strip(), "authority_name required")
        _require(isinstance(self.authority_version, str) and self.authority_version.strip(), "authority_version required")
        _require(_is_number(self.full_timestep_s) and float(self.full_timestep_s) > 0.0, "full_timestep_s must be > 0")
        _require(isinstance(self.n_steps, int) and 1 <= self.n_steps <= 10000, "n_steps must be int in [1, 10000]")
        _require(isinstance(self.linear_only, bool), "linear_only must be bool")
        _require(
            _is_number(self.plasma_resistivity_ohm_m) and float(self.plasma_resistivity_ohm_m) > 0.0,
            "plasma_resistivity_ohm_m must be > 0",
        )
        _require(
            isinstance(self.max_solving_iterations, int) and 1 <= self.max_solving_iterations <= 500,
            "max_solving_iterations must be int in [1, 500]",
        )
        _require(_is_number(self.max_mode_frequency) and float(self.max_mode_frequency) > 0.0, "max_mode_frequency must be > 0")
        _require(_is_number(self.script_timeout_s) and float(self.script_timeout_s) > 0.0, "script_timeout_s must be > 0")
        _require(
            isinstance(self.snapshot_equilibria_every_n, int) and self.snapshot_equilibria_every_n >= 0,
            "snapshot_equilibria_every_n must be int >= 0 (0 disables mid-run snapshots)",
        )
        if self.min_dIy_dI is not None:
            _require(_is_number(self.min_dIy_dI) and float(self.min_dIy_dI) >= 0.0, "min_dIy_dI must be >= 0 or null")
        _require(isinstance(self.notes, str), "notes must be str")

    def to_json_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_evolutive_authority(path: Path) -> EvolutiveAuthority:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"evolutive_authority not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("evolutive_authority must be a JSON object")
    required = [
        "authority_name",
        "authority_version",
        "full_timestep_s",
        "n_steps",
        "linear_only",
        "plasma_resistivity_ohm_m",
        "max_solving_iterations",
        "max_mode_frequency",
        "script_timeout_s",
    ]
    missing = [k for k in required if k not in obj]
    if missing:
        raise ValueError(f"evolutive_authority missing required keys: {missing}")
    ea = EvolutiveAuthority(
        authority_name=str(obj["authority_name"]),
        authority_version=str(obj["authority_version"]),
        full_timestep_s=float(obj["full_timestep_s"]),
        n_steps=int(obj["n_steps"]),
        linear_only=bool(obj["linear_only"]),
        plasma_resistivity_ohm_m=float(obj["plasma_resistivity_ohm_m"]),
        max_solving_iterations=int(obj["max_solving_iterations"]),
        max_mode_frequency=float(obj["max_mode_frequency"]),
        script_timeout_s=float(obj["script_timeout_s"]),
        snapshot_equilibria_every_n=int(obj.get("snapshot_equilibria_every_n", 5)),
        min_dIy_dI=(float(obj["min_dIy_dI"]) if obj.get("min_dIy_dI") is not None else None),
        notes=str(obj.get("notes", "")),
    )
    ea.validate()
    return ea


def write_evolutive_authority(inputs_dir: Path, authority: EvolutiveAuthority) -> Path:
    """Snapshot evolutive authority under inputs/evolutive_authority/."""
    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "evolutive_authority"
    root.mkdir(parents=True, exist_ok=True)
    authority.validate()
    (root / "evolutive_authority.json").write_text(
        json.dumps(authority.to_json_dict(), indent=2) + "\n", encoding="utf-8"
    )
    return root
