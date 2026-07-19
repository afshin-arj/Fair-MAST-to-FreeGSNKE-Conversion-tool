"""Voltage-map authority: FAIR-MAST voltage channels → FreeGSNKE active vector.

Fail-closed. Drive modes (declared explicitly per circuit):

- ``identity|sum|mean`` — measured FAIR-MAST Level-2 voltages (primary drive).
- ``from_current_ohmic`` — no voltage channel but mapped currents exist;
  ``V = sign * scale * I_circuit(t) * R_circuit`` using FreeGSNKE machine
  coil resistance after load (snapshotted at evolutive runtime).
- ``default`` + ``default_V`` — zero-drive (or declared constant) only when
  explicitly required; classic MAST production maps have no divertor zero-drives.
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


_MEASURED_COMBINES = {"identity", "sum", "mean"}
_ALL_COMBINES = _MEASURED_COMBINES | {"default", "from_current_ohmic"}


@dataclass(frozen=True)
class VoltageMap:
    version: str
    machine_active_circuit_order: List[str]
    circuits: Dict[str, Dict[str, Any]]
    notes: str = ""
    machine_circuits_without_fairmast_drive: Optional[List[str]] = None


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
    without = obj.get("machine_circuits_without_fairmast_drive")
    if without is not None:
        if not isinstance(without, list) or not all(isinstance(x, str) and x for x in without):
            raise VoltageMapError(
                "machine_circuits_without_fairmast_drive must be a string list when present"
            )
    return VoltageMap(
        version=str(obj.get("version", "")),
        machine_active_circuit_order=[str(x) for x in order],
        circuits=circuits,
        notes=str(obj.get("notes", "")),
        machine_circuits_without_fairmast_drive=(
            [str(x) for x in without] if isinstance(without, list) else None
        ),
    )


def _default_combine(chans: List[str]) -> str:
    if len(chans) == 1:
        return "identity"
    if len(chans) > 1:
        return "sum"
    return "default"


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

    if vmap.machine_circuits_without_fairmast_drive is not None:
        for name in vmap.machine_circuits_without_fairmast_drive:
            if name not in seen:
                report["ok"] = False
                report["errors"].append(
                    f"machine_circuits_without_fairmast_drive_unknown:{name}"
                )

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
        combine = str(spec.get("combine", _default_combine(chans)))
        if combine not in _ALL_COMBINES:
            report["ok"] = False
            report["errors"].append(
                f"circuits.{name}: combine must be identity|sum|mean|default|from_current_ohmic"
            )
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
        elif combine == "from_current_ohmic":
            if chans:
                report["ok"] = False
                report["errors"].append(
                    f"circuits.{name}: from_current_ohmic must have empty voltage_channels "
                    "(use measured combine when FAIR-MAST V exists)"
                )
            cur = spec.get("current_circuit", name)
            if not isinstance(cur, str) or not cur.strip():
                report["ok"] = False
                report["errors"].append(
                    f"circuits.{name}: from_current_ohmic requires current_circuit string "
                    "(column name in pf_currents.csv)"
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
            # Optional explicit R (usually filled at evolutive from FreeGSNKE coil_resist)
            if "coil_resist_ohm" in spec and spec["coil_resist_ohm"] is not None:
                try:
                    r = float(spec["coil_resist_ohm"])
                    if not (r > 0.0):
                        report["ok"] = False
                        report["errors"].append(
                            f"circuits.{name}: coil_resist_ohm must be > 0 when provided"
                        )
                except Exception:
                    report["ok"] = False
                    report["errors"].append(f"circuits.{name}: coil_resist_ohm must be numeric")
        else:
            if not chans:
                report["ok"] = False
                report["errors"].append(
                    f"circuits.{name}: measured combine requires non-empty voltage_channels "
                    "(or use combine=default / from_current_ohmic)"
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


def voltage_map_drive_summary(vmap: VoltageMap) -> Dict[str, Any]:
    """Count circuits by drive mode for doctor / SUMMARY banners."""
    n_measured = 0
    n_ohmic = 0
    n_zero = 0
    measured: List[str] = []
    ohmic: List[str] = []
    zero_drive: List[str] = []
    for name in vmap.machine_active_circuit_order:
        spec = vmap.circuits.get(name) or {}
        chans = list(spec.get("voltage_channels") or [])
        combine = str(spec.get("combine", _default_combine(chans)))
        if combine in _MEASURED_COMBINES:
            n_measured += 1
            measured.append(name)
        elif combine == "from_current_ohmic":
            n_ohmic += 1
            ohmic.append(name)
        else:
            n_zero += 1
            zero_drive.append(name)
    total = len(vmap.machine_active_circuit_order)
    if n_zero:
        zero_bit = f"{n_zero} by declared 0 V (no FAIR-MAST drive)"
    else:
        zero_bit = "0 by declared 0 V"
    line = (
        f"{n_measured}/{total} active circuits driven by measured FAIR-MAST V; "
        f"{n_ohmic} by I*R (from_current_ohmic); "
        f"{zero_bit}"
    )
    return {
        "n_measured": n_measured,
        "n_ohmic": n_ohmic,
        "n_zero_drive": n_zero,
        "n_total": total,
        "measured": measured,
        "ohmic": ohmic,
        "zero_drive": zero_drive,
        "line": line,
    }


def write_resolved_voltage_map(run_dir: Path, vmap: VoltageMap) -> Path:
    out_dir = Path(run_dir) / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "voltage_map.resolved.json"
    payload: Dict[str, Any] = {
        "version": vmap.version,
        "notes": vmap.notes,
        "machine_active_circuit_order": vmap.machine_active_circuit_order,
        "circuits": vmap.circuits,
    }
    if vmap.machine_circuits_without_fairmast_drive is not None:
        payload["machine_circuits_without_fairmast_drive"] = (
            vmap.machine_circuits_without_fairmast_drive
        )
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out_path


def apply_voltage_map(
    raw_csv: Path,
    out_csv: Path,
    vmap: VoltageMap,
    *,
    pf_currents_csv: Optional[Path] = None,
    coil_resist_by_circuit: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Apply voltage_map to pf_voltages_raw.csv → pf_voltages.csv (circuit columns).

    ``from_current_ohmic`` circuits require ``pf_currents_csv``. When
    ``coil_resist_by_circuit`` provides R for a circuit, V=I×R is written
    immediately; otherwise the column is left NaN and marked
    ``deferred_ohmic=true`` for evolutive runtime fill from FreeGSNKE
    ``coil_resist`` (fail-closed there if R still unavailable).
    """
    report: Dict[str, Any] = {
        "ok": True,
        "errors": [],
        "circuits": {},
        "n_mapped": 0,
        "n_default_zero": 0,
        "n_ohmic": 0,
        "n_ohmic_deferred": 0,
        "order": list(vmap.machine_active_circuit_order),
        "drive_summary": voltage_map_drive_summary(vmap),
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

    currents_df: Optional[pd.DataFrame] = None
    needs_currents = any(
        str((vmap.circuits.get(c) or {}).get("combine", "")) == "from_current_ohmic"
        for c in vmap.machine_active_circuit_order
    )
    if needs_currents:
        if pf_currents_csv is None or not Path(pf_currents_csv).exists():
            report["ok"] = False
            report["errors"].append(
                "from_current_ohmic requires pf_currents.csv "
                "(coil_map must apply before voltage_map)"
            )
            return report
        currents_df = pd.read_csv(Path(pf_currents_csv))
        if "time" not in currents_df.columns:
            report["ok"] = False
            report["errors"].append("pf_currents.csv missing 'time' column")
            return report

    out = pd.DataFrame({"time": df["time"].to_numpy(dtype=float)})
    n = int(out.shape[0])
    t_out = out["time"].to_numpy(dtype=float)

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

        if combine == "from_current_ohmic":
            assert currents_df is not None
            cur_name = str(spec.get("current_circuit", circuit))
            if cur_name not in currents_df.columns:
                report["ok"] = False
                report["errors"].append(
                    f"missing_current_circuit:{circuit}<-{cur_name} "
                    "(need column in pf_currents.csv)"
                )
                continue
            scale = float(spec.get("scale", 1.0))
            sign = float(spec.get("sign", 1))
            t_i = currents_df["time"].to_numpy(dtype=float)
            i_raw = currents_df[cur_name].to_numpy(dtype=float)
            mask = np.isfinite(t_i) & np.isfinite(i_raw)
            n_finite_i = int(mask.sum())
            if n_finite_i < 2:
                report["ok"] = False
                report["errors"].append(
                    f"insufficient_finite_current_samples:{circuit}<-{cur_name} "
                    f"(finite={n_finite_i}/{i_raw.size}; need >=2)"
                )
                continue
            i_on_v_time = np.interp(t_out, t_i[mask], i_raw[mask])

            r_ohm: Optional[float] = None
            if coil_resist_by_circuit and circuit in coil_resist_by_circuit:
                r_ohm = float(coil_resist_by_circuit[circuit])
            elif spec.get("coil_resist_ohm") is not None:
                r_ohm = float(spec["coil_resist_ohm"])

            if r_ohm is not None:
                if not (r_ohm > 0.0) or not np.isfinite(r_ohm):
                    report["ok"] = False
                    report["errors"].append(
                        f"invalid_coil_resist_ohm:{circuit} value={r_ohm} "
                        "(fail-closed; R must be finite and > 0)"
                    )
                    continue
                vals = sign * scale * i_on_v_time * r_ohm
                out[circuit] = vals
                report["circuits"][circuit] = {
                    "combine": "from_current_ohmic",
                    "current_circuit": cur_name,
                    "scale": scale,
                    "sign": sign,
                    "coil_resist_ohm": r_ohm,
                    "deferred_ohmic": False,
                    "n_finite_current": n_finite_i,
                    "notes": spec.get("notes", ""),
                }
                report["n_ohmic"] += 1
            else:
                # Defer V=I×R to evolutive (FreeGSNKE coil_resist after load).
                out[circuit] = np.full(n, np.nan, dtype=float)
                report["circuits"][circuit] = {
                    "combine": "from_current_ohmic",
                    "current_circuit": cur_name,
                    "scale": scale,
                    "sign": sign,
                    "deferred_ohmic": True,
                    "n_finite_current": n_finite_i,
                    "notes": spec.get("notes", ""),
                }
                report["n_ohmic"] += 1
                report["n_ohmic_deferred"] += 1
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
