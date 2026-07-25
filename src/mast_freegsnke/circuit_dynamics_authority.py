"""Cited active-circuit R/L authority for ADR-004 planner (never invent silently)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .planner import CircuitDynamics, PlannerError, extract_circuit_dynamics_from_freegsnke_machine


class CircuitDynamicsAuthorityError(ValueError):
    pass


ALLOWED_L_MODELS = frozenset({"diagonal_self_only", "full_matrix"})
ALLOWED_MISSING = frozenset({"fail", "freegsnke_active_block_fill"})


@dataclass(frozen=True)
class CircuitRL:
    R_ohm: float
    L_henry: float
    notes: str = ""

    def validate(self, name: str) -> None:
        if not isinstance(self.R_ohm, (int, float)) or float(self.R_ohm) <= 0:
            raise CircuitDynamicsAuthorityError(f"{name}: R_ohm must be > 0")
        if not isinstance(self.L_henry, (int, float)) or float(self.L_henry) <= 0:
            raise CircuitDynamicsAuthorityError(f"{name}: L_henry must be > 0")


@dataclass(frozen=True)
class CircuitDynamicsAuthority:
    authority_name: str
    authority_version: str
    status: str
    circuits: Dict[str, CircuitRL]
    citation: Optional[str] = None
    L_model: str = "diagonal_self_only"
    missing_circuits_policy: str = "freegsnke_active_block_fill"
    # Path B1b: when True, keep FreeGSNKE off-diagonal mutuals and overlay cited R + L_ii.
    prefer_freegsnke_mutuals: bool = True
    notes: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def awaiting(self) -> bool:
        st = self.status.strip().lower()
        return st in {"awaiting_authority", "awaiting", "empty", ""} or not self.circuits

    def validate(self) -> None:
        if not self.authority_name.strip():
            raise CircuitDynamicsAuthorityError("authority_name required")
        if self.L_model not in ALLOWED_L_MODELS:
            raise CircuitDynamicsAuthorityError(
                f"L_model must be one of {sorted(ALLOWED_L_MODELS)}"
            )
        if self.missing_circuits_policy not in ALLOWED_MISSING:
            raise CircuitDynamicsAuthorityError(
                f"missing_circuits_policy must be one of {sorted(ALLOWED_MISSING)}"
            )
        if self.awaiting:
            return
        if not self.citation or not str(self.citation).strip():
            raise CircuitDynamicsAuthorityError(
                "circuit_dynamics with circuits requires citation — never invent R/L"
            )
        for name, rl in self.circuits.items():
            rl.validate(name)

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "authority_name": self.authority_name,
            "authority_version": self.authority_version,
            "status": self.status,
            "citation": self.citation,
            "L_model": self.L_model,
            "missing_circuits_policy": self.missing_circuits_policy,
            "prefer_freegsnke_mutuals": bool(self.prefer_freegsnke_mutuals),
            "circuits": {
                k: {"R_ohm": float(v.R_ohm), "L_henry": float(v.L_henry), "notes": v.notes}
                for k, v in self.circuits.items()
            },
            "notes": self.notes,
        }


def load_circuit_dynamics_authority(path: Path) -> CircuitDynamicsAuthority:
    path = Path(path)
    if not path.exists():
        raise CircuitDynamicsAuthorityError(f"circuit_dynamics_authority not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise CircuitDynamicsAuthorityError("circuit_dynamics_authority must be a JSON object")
    raw_circuits = obj.get("circuits") or {}
    if not isinstance(raw_circuits, Mapping):
        raise CircuitDynamicsAuthorityError("circuits must be an object")
    circuits: Dict[str, CircuitRL] = {}
    for name, entry in raw_circuits.items():
        if not isinstance(entry, Mapping):
            raise CircuitDynamicsAuthorityError(f"circuit {name!r} must be an object")
        circuits[str(name)] = CircuitRL(
            R_ohm=float(entry["R_ohm"]),
            L_henry=float(entry["L_henry"]),
            notes=str(entry.get("notes", "")),
        )
    prefer_m = obj.get("prefer_freegsnke_mutuals", True)
    if not isinstance(prefer_m, bool):
        raise CircuitDynamicsAuthorityError(
            "prefer_freegsnke_mutuals must be a JSON boolean"
        )
    auth = CircuitDynamicsAuthority(
        authority_name=str(obj.get("authority_name", "circuit_dynamics")),
        authority_version=str(obj.get("authority_version", "1.0.0")),
        status=str(obj.get("status", "awaiting_authority")),
        circuits=circuits,
        citation=(str(obj["citation"]) if obj.get("citation") else None),
        L_model=str(obj.get("L_model", "diagonal_self_only")),
        missing_circuits_policy=str(
            obj.get("missing_circuits_policy", "freegsnke_active_block_fill")
        ),
        prefer_freegsnke_mutuals=prefer_m,
        notes=str(obj.get("notes", "")),
        raw=obj,
    )
    auth.validate()
    return auth


def write_circuit_dynamics_authority(inputs_dir: Path, auth: CircuitDynamicsAuthority) -> Path:
    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "circuit_dynamics_authority"
    root.mkdir(parents=True, exist_ok=True)
    auth.validate()
    path = root / "circuit_dynamics_authority.json"
    path.write_text(json.dumps(auth.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def build_circuit_dynamics_from_authority(
    auth: CircuitDynamicsAuthority,
    *,
    circuit_order: Sequence[str],
    machine_dir: Optional[Path] = None,
    freegsnke_fill: Optional[CircuitDynamics] = None,
) -> Tuple[CircuitDynamics, Dict[str, Any]]:
    """Build planner CircuitDynamics from cited table; optionally fill gaps from FreeGSNKE.

    Path B1b: when ``prefer_freegsnke_mutuals`` (default) or ``L_model=full_matrix``,
    start from FreeGSNKE active-block R/L so off-diagonal mutuals are retained, then
    overlay cited R and L_ii. Pure diagonal is allowed only as a declared fallback.
    """
    auth.validate()
    if auth.awaiting:
        raise CircuitDynamicsAuthorityError(
            "circuit_dynamics_authority awaiting — populate cited R/L before planner"
        )
    order = [str(c) for c in circuit_order]
    missing = [c for c in order if c not in auth.circuits]
    want_mutuals = bool(auth.prefer_freegsnke_mutuals) or auth.L_model == "full_matrix"
    fill_notes: Dict[str, Any] = {
        "L_model": auth.L_model,
        "prefer_freegsnke_mutuals": bool(auth.prefer_freegsnke_mutuals),
        "citation": auth.citation,
        "user_table_circuits": sorted(auth.circuits.keys()),
        "filled_from_freegsnke": [],
        "missing_at_start": list(missing),
        "mutuals": "unknown",
    }
    source_parts = [f"circuit_dynamics_authority:{auth.citation}"]
    fill = freegsnke_fill

    if missing and auth.missing_circuits_policy == "fail" and not want_mutuals:
        raise CircuitDynamicsAuthorityError(
            f"circuit_dynamics_authority missing circuits: {missing} "
            f"(set missing_circuits_policy=freegsnke_active_block_fill or add R/L)"
        )

    need_fill = bool(missing) or want_mutuals
    if fill is None and need_fill:
        if machine_dir is None:
            if missing:
                raise CircuitDynamicsAuthorityError(
                    f"missing circuits {missing} need FreeGSNKE fill but machine_dir not provided"
                )
        else:
            try:
                fill = extract_circuit_dynamics_from_freegsnke_machine(
                    machine_dir=Path(machine_dir),
                    circuit_order=order,
                )
            except PlannerError as e:
                if missing:
                    raise CircuitDynamicsAuthorityError(
                        f"missing circuits {missing} and FreeGSNKE fill failed: {e}"
                    ) from e
                fill = None
                fill_notes["mutuals_extract_error"] = f"{type(e).__name__}: {e}"

    if fill is not None:
        if fill.circuit_order != order:
            raise CircuitDynamicsAuthorityError("freegsnke fill order mismatch")
        source_parts.append(fill.source)
        fill_notes["filled_from_freegsnke"] = list(missing)
        fill_notes["freegsnke_base_matrix"] = True
        R = np.asarray(fill.R_ohm, dtype=float).copy()
        L = np.asarray(fill.L_henry, dtype=float).copy()
        off = L.copy()
        np.fill_diagonal(off, 0.0)
        if float(np.max(np.abs(off))) > 0.0:
            fill_notes["mutuals"] = "freegsnke_offdiag_retained_cited_Lii_overlay"
            source_parts.append("prefer_freegsnke_mutuals=true")
        else:
            fill_notes["mutuals"] = "freegsnke_base_but_offdiag_zero"
    else:
        if missing:
            raise CircuitDynamicsAuthorityError(
                f"circuit_dynamics_authority missing circuits: {missing}"
            )
        R = np.zeros(len(order), dtype=float)
        L = np.zeros((len(order), len(order)), dtype=float)
        fill_notes["freegsnke_base_matrix"] = False
        fill_notes["mutuals"] = "neglected_diagonal_self_only_declared"
        source_parts.append("L_model=diagonal_self_only(mutuals_neglected_declared)")

    for j, name in enumerate(order):
        if name not in auth.circuits:
            continue
        rl = auth.circuits[name]
        R[j] = float(rl.R_ohm)
        L[j, j] = float(rl.L_henry)

    dyn = CircuitDynamics(
        circuit_order=order,
        R_ohm=R,
        L_henry=L,
        source=" + ".join(source_parts),
        notes=(
            f"{auth.notes} | fill={fill_notes['filled_from_freegsnke']} | "
            f"L_model={auth.L_model} | mutuals={fill_notes['mutuals']}"
        ),
    )
    dyn.validate()
    return dyn, fill_notes
