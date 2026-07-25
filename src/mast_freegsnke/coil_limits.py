"""Coil I/V limits authority — ADR-004 Phase 2 hard gate (never invent limits)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


class CoilLimitsError(ValueError):
    pass


@dataclass(frozen=True)
class CircuitLimit:
    Imax_A: float
    Vmax_V: float
    Imin_A: Optional[float] = None
    Vmin_V: Optional[float] = None
    notes: str = ""

    def validate(self, name: str) -> None:
        if not isinstance(self.Imax_A, (int, float)) or float(self.Imax_A) <= 0:
            raise CoilLimitsError(f"{name}: Imax_A must be > 0 (got {self.Imax_A!r})")
        if not isinstance(self.Vmax_V, (int, float)) or float(self.Vmax_V) <= 0:
            raise CoilLimitsError(f"{name}: Vmax_V must be > 0 (got {self.Vmax_V!r})")
        imin = float(self.Imin_A) if self.Imin_A is not None else -float(self.Imax_A)
        vmin = float(self.Vmin_V) if self.Vmin_V is not None else -float(self.Vmax_V)
        if imin >= float(self.Imax_A):
            raise CoilLimitsError(f"{name}: Imin_A must be < Imax_A")
        if vmin >= float(self.Vmax_V):
            raise CoilLimitsError(f"{name}: Vmin_V must be < Vmax_V")

    def i_bounds(self) -> tuple[float, float]:
        lo = float(self.Imin_A) if self.Imin_A is not None else -float(self.Imax_A)
        return lo, float(self.Imax_A)

    def v_bounds(self) -> tuple[float, float]:
        lo = float(self.Vmin_V) if self.Vmin_V is not None else -float(self.Vmax_V)
        return lo, float(self.Vmax_V)

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "Imax_A": float(self.Imax_A),
            "Vmax_V": float(self.Vmax_V),
            "Imin_A": (float(self.Imin_A) if self.Imin_A is not None else None),
            "Vmin_V": (float(self.Vmin_V) if self.Vmin_V is not None else None),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CoilLimitsAuthority:
    authority_name: str
    authority_version: str
    status: str
    circuits: Dict[str, CircuitLimit]
    citation: Optional[str] = None
    notes: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def awaiting(self) -> bool:
        st = self.status.strip().lower()
        return st in {"awaiting_authority", "awaiting", "empty", ""} or not self.circuits

    def validate(self) -> None:
        if not self.authority_name.strip():
            raise CoilLimitsError("authority_name required")
        if not self.authority_version.strip():
            raise CoilLimitsError("authority_version required")
        if self.awaiting:
            return
        if not self.citation or not str(self.citation).strip():
            raise CoilLimitsError(
                "coil_limits with non-empty circuits requires citation (plant doc / paper URL) "
                "— never invent Imax/Vmax"
            )
        for name, lim in self.circuits.items():
            lim.validate(name)

    def require_ready(self, circuit_order: List[str]) -> None:
        """Fail-closed for planner solve."""
        self.validate()
        if self.awaiting:
            raise CoilLimitsError(
                "coil_limits_authority status=awaiting_authority or circuits empty — "
                "populate per-circuit Imax_A/Vmax_V with citation before execute_planner "
                "(ADR-004 hard gate; never invent limits)"
            )
        missing = [c for c in circuit_order if c not in self.circuits]
        if missing:
            raise CoilLimitsError(
                f"coil_limits missing circuits required by voltage_map order: {missing}"
            )

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "authority_name": self.authority_name,
            "authority_version": self.authority_version,
            "status": self.status,
            "citation": self.citation,
            "circuits": {k: v.to_json_dict() for k, v in self.circuits.items()},
            "notes": self.notes,
        }


def load_coil_limits(path: Path) -> CoilLimitsAuthority:
    path = Path(path)
    if not path.exists():
        raise CoilLimitsError(f"coil_limits_authority not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise CoilLimitsError("coil_limits_authority must be a JSON object")
    raw_circuits = obj.get("circuits") or {}
    if not isinstance(raw_circuits, Mapping):
        raise CoilLimitsError("circuits must be an object")
    circuits: Dict[str, CircuitLimit] = {}
    for name, entry in raw_circuits.items():
        if not isinstance(entry, Mapping):
            raise CoilLimitsError(f"circuit {name!r} must be an object")
        circuits[str(name)] = CircuitLimit(
            Imax_A=float(entry["Imax_A"]),
            Vmax_V=float(entry["Vmax_V"]),
            Imin_A=(float(entry["Imin_A"]) if entry.get("Imin_A") is not None else None),
            Vmin_V=(float(entry["Vmin_V"]) if entry.get("Vmin_V") is not None else None),
            notes=str(entry.get("notes", "")),
        )
    auth = CoilLimitsAuthority(
        authority_name=str(obj.get("authority_name", "coil_limits")),
        authority_version=str(obj.get("authority_version", "0.1.0")),
        status=str(obj.get("status", "awaiting_authority")),
        circuits=circuits,
        citation=(str(obj["citation"]) if obj.get("citation") else None),
        notes=str(obj.get("notes", "")),
        raw=obj,
    )
    auth.validate()
    return auth


def write_coil_limits(inputs_dir: Path, auth: CoilLimitsAuthority) -> Path:
    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "coil_limits_authority"
    root.mkdir(parents=True, exist_ok=True)
    auth.validate()
    path = root / "coil_limits_authority.json"
    path.write_text(json.dumps(auth.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def coil_limits_status_line(auth: CoilLimitsAuthority) -> str:
    if auth.awaiting:
        return (
            "[INFO] coil_limits: awaiting_authority — planner blocked until cited "
            "Imax_A/Vmax_V per circuit (ADR-004)"
        )
    return (
        f"[OK] coil_limits: {len(auth.circuits)} circuits "
        f"citation={auth.citation!r}"
    )
