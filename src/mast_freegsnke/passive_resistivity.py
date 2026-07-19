"""Optional passive resistivity authority (awaiting published ρ — never invent)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


class PassiveResistivityError(ValueError):
    pass


@dataclass(frozen=True)
class PassiveResistivityAuthority:
    version: str
    status: str
    notes: str
    components: Dict[str, Any]
    raw: Dict[str, Any]

    @property
    def awaiting(self) -> bool:
        return self.status.strip().lower() in {
            "awaiting_authority",
            "awaiting",
            "empty",
            "",
        } or not self.components


def load_passive_resistivity(path: Path) -> PassiveResistivityAuthority:
    path = Path(path)
    if not path.exists():
        raise PassiveResistivityError(f"passive_resistivity authority not found: {path}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise PassiveResistivityError(f"invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise PassiveResistivityError("root must be object")
    components = obj.get("components") or {}
    if not isinstance(components, dict):
        raise PassiveResistivityError("components must be object")
    # Fail-closed: any component must have explicit resistivity_ohm_m > 0 and source.
    for name, entry in components.items():
        if not isinstance(entry, dict):
            raise PassiveResistivityError(f"component {name!r} must be object")
        rho = entry.get("resistivity_ohm_m")
        src = entry.get("source")
        if rho is None or not isinstance(rho, (int, float)) or float(rho) <= 0:
            raise PassiveResistivityError(
                f"component {name!r}: resistivity_ohm_m must be > 0 (got {rho!r})"
            )
        if not src or not str(src).strip():
            raise PassiveResistivityError(f"component {name!r}: source citation required")
    return PassiveResistivityAuthority(
        version=str(obj.get("version", "")),
        status=str(obj.get("status", "awaiting_authority")),
        notes=str(obj.get("notes", "")),
        components={str(k): v for k, v in components.items()},
        raw=obj,
    )


def passive_resistivity_status_line(
    path: Optional[str] = None,
    auth: Optional[PassiveResistivityAuthority] = None,
) -> str:
    if not path:
        return (
            "[INFO] passive_resistivity authority not configured — "
            "FreeGSNKE passives stay empty (do not invent resistivity)"
        )
    if auth is None:
        return f"[INFO] passive_resistivity: path set ({path}) but not loaded"
    if auth.awaiting:
        return (
            "[INFO] FreeGSNKE passives: awaiting passive_resistivity channels "
            f"({path}; FAIR-MAST pf_passive has geometry but no resistivity)"
        )
    return (
        f"[OK] passive_resistivity: {len(auth.components)} component(s) declared "
        f"({path}) — rebuild machine to wire FreeGSNKE passives"
    )
