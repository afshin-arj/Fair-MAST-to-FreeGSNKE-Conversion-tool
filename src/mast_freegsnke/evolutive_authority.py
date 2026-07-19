"""Evolutive (time-dependent) FreeGSNKE execution authority.

Fail-closed: all numerics required for nl_solver / nlstepper must be declared.
Profile shape parameters (alpha_m/alpha_n/fvac) are held from the inverse IC.
Optional declared law ``scale_paxis_with_ip`` scales paxis with measured Ip(t)/Ip(t0)
— never invents profile numbers from thin air.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import json


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
    linear_only: bool
    plasma_resistivity_ohm_m: float
    max_solving_iterations: int
    max_mode_frequency: float
    script_timeout_s: float
    n_steps: Optional[int] = None
    cover_window: bool = False
    max_steps: int = 50
    scale_paxis_with_ip: bool = False
    snapshot_equilibria_every_n: int = 5
    min_dIy_dI: Optional[float] = None
    notes: str = ""

    def validate(self) -> None:
        _require(isinstance(self.authority_name, str) and self.authority_name.strip(), "authority_name required")
        _require(isinstance(self.authority_version, str) and self.authority_version.strip(), "authority_version required")
        _require(_is_number(self.full_timestep_s) and float(self.full_timestep_s) > 0.0, "full_timestep_s must be > 0")
        _require(isinstance(self.cover_window, bool), "cover_window must be bool")
        _require(isinstance(self.max_steps, int) and 1 <= self.max_steps <= 10000, "max_steps must be int in [1, 10000]")
        if self.cover_window:
            if self.n_steps is not None:
                _require(
                    isinstance(self.n_steps, int) and 1 <= self.n_steps <= 10000,
                    "n_steps override must be int in [1, 10000] when provided with cover_window",
                )
        else:
            _require(
                isinstance(self.n_steps, int) and 1 <= int(self.n_steps) <= 10000,
                "n_steps must be int in [1, 10000] when cover_window is false",
            )
        _require(isinstance(self.linear_only, bool), "linear_only must be bool")
        _require(isinstance(self.scale_paxis_with_ip, bool), "scale_paxis_with_ip must be bool")
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


def resolve_n_steps(
    authority: EvolutiveAuthority,
    *,
    t_start: float,
    t_end: float,
) -> Dict[str, Any]:
    """Resolve step count from cover_window / max_steps / optional n_steps override.

    When ``cover_window``: ``n = min(max_steps, max(1, ceil((t_end-t_start)/dt)))``
    unless ``n_steps`` is set as an explicit override.
    """
    dt = float(authority.full_timestep_s)
    span = float(t_end) - float(t_start)
    n_from_window = max(1, int(math.ceil(span / dt))) if span > 0.0 else 1
    if authority.cover_window:
        if authority.n_steps is not None:
            n = int(authority.n_steps)
            mode = "n_steps_override"
        else:
            n = min(int(authority.max_steps), n_from_window)
            mode = "cover_window"
    else:
        n = int(authority.n_steps)  # type: ignore[arg-type]
        mode = "fixed_n_steps"
    return {
        "n_steps": int(n),
        "mode": mode,
        "full_timestep_s": dt,
        "t_start": float(t_start),
        "t_end": float(t_end),
        "window_span_s": float(span),
        "n_from_window": int(n_from_window),
        "max_steps": int(authority.max_steps),
        "cover_window": bool(authority.cover_window),
        "n_steps_override": authority.n_steps,
    }


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
        "linear_only",
        "plasma_resistivity_ohm_m",
        "max_solving_iterations",
        "max_mode_frequency",
        "script_timeout_s",
    ]
    missing = [k for k in required if k not in obj]
    if missing:
        raise ValueError(f"evolutive_authority missing required keys: {missing}")

    cover_window = bool(obj.get("cover_window", False))
    n_steps_raw = obj.get("n_steps", None)
    if n_steps_raw is None and not cover_window:
        raise ValueError(
            "evolutive_authority missing n_steps "
            "(required when cover_window is false; omit only with cover_window=true)"
        )
    n_steps = int(n_steps_raw) if n_steps_raw is not None else None

    ea = EvolutiveAuthority(
        authority_name=str(obj["authority_name"]),
        authority_version=str(obj["authority_version"]),
        full_timestep_s=float(obj["full_timestep_s"]),
        n_steps=n_steps,
        cover_window=cover_window,
        max_steps=int(obj.get("max_steps", 50)),
        linear_only=bool(obj["linear_only"]),
        scale_paxis_with_ip=bool(obj.get("scale_paxis_with_ip", False)),
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
