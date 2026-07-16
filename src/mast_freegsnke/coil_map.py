
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd


class CoilMapError(ValueError):
    pass


@dataclass(frozen=True)
class CoilMap:
    """
    Deterministic mapping from experimental PF current columns to FreeGSNKE coil names.

    Schema v1.0 (legacy, one exp column -> one coil):
    {
      "version": "1.0",
      "mapping": {
        "exp_column_name": {"coil": "FreeGSNKE_CoilName", "scale": 1.0, "sign": 1}
      }
    }

    Schema v1.1 (circuit-centric, explicit combine for multi-feed circuits):
    {
      "version": "1.1",
      "circuits": {
        "P2_inner": {
          "exp_columns": ["P2IL FEED", "P2IU FEED"],
          "combine": "sum",
          "scale": 1.0,
          "sign": 1
        }
      }
    }
    """
    mapping: Dict[str, Dict[str, Any]]
    circuits: Dict[str, Dict[str, Any]]


def load_coil_map(path: Path) -> CoilMap:
    obj = json.loads(path.read_text())
    if not isinstance(obj, dict):
        raise CoilMapError("coil_map JSON root must be an object")
    mapping = obj.get("mapping", {}) or {}
    circuits = obj.get("circuits", {}) or {}
    if not isinstance(mapping, dict):
        raise CoilMapError("'mapping' must be an object")
    if not isinstance(circuits, dict):
        raise CoilMapError("'circuits' must be an object")
    if not mapping and not circuits:
        raise CoilMapError("coil_map must provide non-empty 'mapping' and/or 'circuits'")
    return CoilMap(mapping=mapping, circuits=circuits)


def validate_coil_map(coil_map: CoilMap) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "ok": True,
        "errors": [],
        "n": len(coil_map.mapping) + len(coil_map.circuits),
    }
    for exp_col, spec in coil_map.mapping.items():
        if not isinstance(spec, dict):
            report["ok"] = False
            report["errors"].append(f"{exp_col}: mapping spec must be an object")
            continue
        coil = spec.get("coil")
        if not coil or not isinstance(coil, str):
            report["ok"] = False
            report["errors"].append(f"{exp_col}: missing 'coil' string")
        sign = spec.get("sign", 1)
        if sign not in (-1, 1):
            report["ok"] = False
            report["errors"].append(f"{exp_col}: sign must be +1 or -1")
        try:
            float(spec.get("scale", 1.0))
        except Exception:
            report["ok"] = False
            report["errors"].append(f"{exp_col}: scale must be numeric")

    for coil, spec in coil_map.circuits.items():
        if not isinstance(spec, dict):
            report["ok"] = False
            report["errors"].append(f"circuits.{coil}: must be an object")
            continue
        cols = spec.get("exp_columns")
        if not isinstance(cols, list) or not cols or not all(isinstance(c, str) and c for c in cols):
            report["ok"] = False
            report["errors"].append(f"circuits.{coil}: exp_columns must be a non-empty string list")
        combine = str(spec.get("combine", "sum" if isinstance(cols, list) and len(cols) > 1 else "identity"))
        if combine not in {"identity", "sum", "mean"}:
            report["ok"] = False
            report["errors"].append(f"circuits.{coil}: combine must be identity|sum|mean")
        if combine == "identity" and isinstance(cols, list) and len(cols) != 1:
            report["ok"] = False
            report["errors"].append(f"circuits.{coil}: identity combine requires exactly one exp column")
        sign = spec.get("sign", 1)
        if sign not in (-1, 1):
            report["ok"] = False
            report["errors"].append(f"circuits.{coil}: sign must be +1 or -1")
        try:
            float(spec.get("scale", 1.0))
        except Exception:
            report["ok"] = False
            report["errors"].append(f"circuits.{coil}: scale must be numeric")
    return report


def write_resolved_coil_map(run_dir: Path, coil_map: CoilMap) -> Path:
    out_dir = run_dir / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "coil_map.resolved.json"
    out_path.write_text(
        json.dumps(
            {"version": "1.1", "mapping": coil_map.mapping, "circuits": coil_map.circuits},
            indent=2,
            sort_keys=True,
        )
    )
    return out_path


def apply_coil_map(
    raw_csv: Path,
    out_csv: Path,
    coil_map: CoilMap,
) -> Dict[str, Any]:
    """Apply explicit coil_map authority to pf_active_raw.csv → pf_currents.csv."""
    report: Dict[str, Any] = {"ok": True, "errors": [], "coils": {}, "n_mapped": 0}
    if not raw_csv.exists():
        report["ok"] = False
        report["errors"].append(f"missing_raw_csv:{raw_csv}")
        return report

    df = pd.read_csv(raw_csv)
    if "time" not in df.columns:
        report["ok"] = False
        report["errors"].append("pf_active_raw.csv missing 'time' column")
        return report

    out = pd.DataFrame({"time": df["time"].to_numpy(dtype=float)})

    # Legacy 1:1 mapping path (reject silent duplicate coil targets)
    coil_to_exp: Dict[str, List[str]] = {}
    for exp_col, spec in coil_map.mapping.items():
        coil = str(spec.get("coil"))
        coil_to_exp.setdefault(coil, []).append(exp_col)
    for coil, exps in sorted(coil_to_exp.items()):
        if len(exps) > 1:
            report["ok"] = False
            report["errors"].append(
                f"duplicate_coil_target:{coil}<-{exps} (use circuits[] with explicit combine)"
            )

    for exp_col, spec in sorted(coil_map.mapping.items(), key=lambda kv: kv[0]):
        coil = str(spec.get("coil"))
        if coil in out.columns:
            continue
        if exp_col not in df.columns:
            report["ok"] = False
            report["errors"].append(f"missing_exp_column:{exp_col}")
            continue
        scale = float(spec.get("scale", 1.0))
        sign = float(spec.get("sign", 1))
        vals = df[exp_col].to_numpy(dtype=float) * scale * sign
        if not np.isfinite(vals).all():
            report["ok"] = False
            report["errors"].append(f"nonfinite_values:{exp_col}->{coil}")
            continue
        out[coil] = vals
        report["coils"][coil] = {"exp_columns": [exp_col], "combine": "identity", "scale": scale, "sign": sign}
        report["n_mapped"] += 1

    # Circuit-centric path with explicit combine
    for coil, spec in sorted(coil_map.circuits.items(), key=lambda kv: kv[0]):
        if coil in out.columns:
            report["ok"] = False
            report["errors"].append(f"duplicate_coil_definition:{coil}")
            continue
        cols = list(spec.get("exp_columns") or [])
        missing = [c for c in cols if c not in df.columns]
        if missing:
            report["ok"] = False
            report["errors"].append(f"missing_exp_columns:{coil}:{missing}")
            continue
        scale = float(spec.get("scale", 1.0))
        sign = float(spec.get("sign", 1))
        combine = str(spec.get("combine", "sum" if len(cols) > 1 else "identity"))
        mat = np.column_stack([df[c].to_numpy(dtype=float) for c in cols])
        if combine == "identity":
            vals = mat[:, 0]
        elif combine == "sum":
            vals = mat.sum(axis=1)
        elif combine == "mean":
            vals = mat.mean(axis=1)
        else:
            report["ok"] = False
            report["errors"].append(f"invalid_combine:{coil}:{combine}")
            continue
        vals = vals * scale * sign
        if not np.isfinite(vals).all():
            report["ok"] = False
            report["errors"].append(f"nonfinite_values:{coil}")
            continue
        out[coil] = vals
        report["coils"][coil] = {"exp_columns": cols, "combine": combine, "scale": scale, "sign": sign}
        report["n_mapped"] += 1

    if not report["ok"]:
        return report

    if report["n_mapped"] == 0:
        report["ok"] = False
        report["errors"].append("coil_map_empty: no columns mapped")
        return report

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)
    report["out_csv"] = str(out_csv)
    return report
