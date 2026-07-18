"""Voltage-map authority: FAIR-MAST voltage channels → FreeGSNKE active vector.

Fail-closed. Circuits without measured voltage must declare ``combine=default``
and ``default_V`` explicitly (zero-drive is an honest declaration, not a hidden
invention of physics).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


class VoltageMapError(ValueError):
    pass


@dataclass(frozen=True)
class VoltageMap:
    version: str
    machine_active_circuit_order: List[str]
    circuits: Dict[str, Dict[str, Any]]
    notes: str = ""


def load_voltage_map(path: Path) -> VoltageMap:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise VoltageMapError("voltage_map JSON root must be an object")
    order = obj.get("machine_active_circuit_order")
    circuits = obj.get("circuits")
    if not isinstance(order, list) or not order or not all(isinstance(x, str) and x for x in order):
        raise VoltageMapError("machine_active_circuit_order must be a non-empty string list")
    if not isinstance(circuits, dict) or not circuits:
        raise VoltageMapError("circuits must be a non-empty object")
    return VoltageMap(
        version=str(obj.get("version", "")),
        machine_active_circuit_order=[str(x) for x in order],
        circuits=circuits,
        notes=str(obj.get("notes", "")),
    )


def validate_voltage_map(vmap: VoltageMap) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "ok": True,
        "errors": [],
        "n_circuits": len(vmap.machine_active_circuit_order),
        "order": list(vmap.machine_active_circuit_order),
    }
    if not vmap.version.strip():
        report["ok"] = False
        report["errors"].append("missing version")

    seen = set()
    for name in vmap.machine_active_circuit_order:
        if name in seen:
            report["ok"] = False
            report["errors"].append(f"duplicate_circuit_in_order:{name}")
        seen.add(name)
        if name not in vmap.circuits:
            report["ok"] = False
            report["errors"].append(f"order_circuit_missing_from_circuits:{name}")

    for name, spec in vmap.circuits.items():
        if name not in seen:
            report["ok"] = False
            report["errors"].append(f"circuits_entry_not_in_order:{name}")
        if not isinstance(spec, dict):
            report["ok"] = False
            report["errors"].append(f"circuits.{name}: must be an object")
            continue
        chans = spec.get("voltage_channels", [])
        if chans is None:
            chans = []
        if not isinstance(chans, list) or not all(isinstance(c, str) for c in chans):
            report["ok"] = False
            report["errors"].append(f"circuits.{name}: voltage_channels must be a string list")
            chans = []
        combine = str(spec.get("combine", "identity" if len(chans) == 1 else ("sum" if len(chans) > 1 else "default")))
        if combine not in {"identity", "sum", "mean", "default"}:
            report["ok"] = False
            report["errors"].append(f"circuits.{name}: combine must be identity|sum|mean|default")
        if combine == "identity" and len(chans) != 1:
            report["ok"] = False
            report["errors"].append(f"circuits.{name}: identity combine requires exactly one voltage channel")
        if combine == "default":
            if "default_V" not in spec:
                report["ok"] = False
                report["errors"].append(
                    f"circuits.{name}: combine=default requires explicit default_V "
                    "(declare zero-drive honestly; do not omit)"
                )
            else:
                try:
                    float(spec["default_V"])
                except Exception:
                    report["ok"] = False
                    report["errors"].append(f"circuits.{name}: default_V must be numeric")
            if chans:
                report["ok"] = False
                report["errors"].append(
                    f"circuits.{name}: combine=default must have empty voltage_channels "
                    "(measured channels use identity|sum|mean)"
                )
        else:
            if not chans:
                report["ok"] = False
                report["errors"].append(
                    f"circuits.{name}: measured combine requires non-empty voltage_channels "
                    "(or use combine=default with default_V)"
                )
            sign = spec.get("sign", 1)
            if sign not in (-1, 1):
                report["ok"] = False
                report["errors"].append(f"circuits.{name}: sign must be +1 or -1")
            try:
                float(spec.get("scale", 1.0))
            except Exception:
                report["ok"] = False
                report["errors"].append(f"circuits.{name}: scale must be numeric")
        notes = spec.get("notes", "")
        if not isinstance(notes, str) or not notes.strip():
            report["ok"] = False
            report["errors"].append(f"circuits.{name}: notes required (document mapping or zero-drive)")
    return report


def write_resolved_voltage_map(run_dir: Path, vmap: VoltageMap) -> Path:
    out_dir = Path(run_dir) / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "voltage_map.resolved.json"
    out_path.write_text(
        json.dumps(
            {
                "version": vmap.version,
                "notes": vmap.notes,
                "machine_active_circuit_order": vmap.machine_active_circuit_order,
                "circuits": vmap.circuits,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return out_path


def apply_voltage_map(
    raw_csv: Path,
    out_csv: Path,
    vmap: VoltageMap,
) -> Dict[str, Any]:
    """Apply voltage_map to pf_voltages_raw.csv → pf_voltages.csv (circuit columns)."""
    report: Dict[str, Any] = {
        "ok": True,
        "errors": [],
        "circuits": {},
        "n_mapped": 0,
        "n_default_zero": 0,
        "order": list(vmap.machine_active_circuit_order),
    }
    raw_csv = Path(raw_csv)
    out_csv = Path(out_csv)
    if not raw_csv.exists():
        report["ok"] = False
        report["errors"].append(f"missing_raw_csv:{raw_csv}")
        return report

    df = pd.read_csv(raw_csv)
    if "time" not in df.columns:
        report["ok"] = False
        report["errors"].append("pf_voltages_raw.csv missing 'time' column")
        return report

    out = pd.DataFrame({"time": df["time"].to_numpy(dtype=float)})
    n = int(out.shape[0])

    for circuit in vmap.machine_active_circuit_order:
        spec = vmap.circuits[circuit]
        combine = str(spec.get("combine", "identity"))
        if combine == "default":
            default_v = float(spec["default_V"])
            out[circuit] = np.full(n, default_v, dtype=float)
            report["circuits"][circuit] = {
                "combine": "default",
                "default_V": default_v,
                "voltage_channels": [],
                "notes": spec.get("notes", ""),
            }
            report["n_default_zero"] += 1
            continue

        chans = list(spec.get("voltage_channels") or [])
        missing = [c for c in chans if c not in df.columns]
        if missing:
            report["ok"] = False
            report["errors"].append(f"missing_voltage_channel:{circuit}<-{missing}")
            continue
        scale = float(spec.get("scale", 1.0))
        sign = float(spec.get("sign", 1))
        cols = [df[c].to_numpy(dtype=float) for c in chans]
        stacked = np.vstack(cols)
        if combine == "identity":
            vals = stacked[0] * scale * sign
        elif combine == "sum":
            vals = stacked.sum(axis=0) * scale * sign
        elif combine == "mean":
            vals = stacked.mean(axis=0) * scale * sign
        else:
            report["ok"] = False
            report["errors"].append(f"unsupported_combine:{circuit}:{combine}")
            continue
        n_finite = int(np.isfinite(vals).sum())
        n_nonfinite = int(vals.size - n_finite)
        if n_finite < 2:
            report["ok"] = False
            report["errors"].append(
                f"insufficient_finite_voltage_samples:{circuit} "
                f"(finite={n_finite}/{vals.size}; need >=2 for interpolation — "
                "refusing to invent fill values)"
            )
            continue
        # Sparse NaNs in FAIR-MAST (e.g. a single edge sample) are recorded honestly;
        # evolutive interpolates using finite samples only — we do not invent fills.
        out[circuit] = vals
        report["circuits"][circuit] = {
            "combine": combine,
            "scale": scale,
            "sign": sign,
            "voltage_channels": chans,
            "n_finite": n_finite,
            "n_nonfinite": n_nonfinite,
            "notes": spec.get("notes", ""),
        }
        report["n_mapped"] += 1

    if report["ok"]:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(out_csv, index=False)
    return report


def snapshot_voltage_map_hash(vmap: VoltageMap, run_dir: Path) -> Dict[str, Any]:
    """Write resolved map + SHA-256 of the resolved JSON into contracts/."""
    import hashlib

    path = write_resolved_voltage_map(run_dir, vmap)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = {"path": str(path.relative_to(run_dir)).replace("\\", "/"), "sha256": digest}
    (Path(run_dir) / "contracts" / "voltage_map.sha256.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return meta
