
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class ContractError(ValueError):
    """Raised when a diagnostic/coil contract is invalid."""


@dataclass(frozen=True)
class TraceSpec:
    """
    Specification of a single time series in a CSV file.

    Required columns:
      - time_col: name of time column (seconds)
      - value_col: name of value column
    Optional:
      - scale: multiplicative factor applied to values (default 1.0)
      - sign: sign factor (+1 or -1), applied after scale (default +1)
    """
    csv: Path
    time_col: str
    value_col: str
    scale: float = 1.0
    sign: float = 1.0

    def apply(self, y):
        return (self.sign * self.scale) * y


@dataclass(frozen=True)
class DiagnosticContract:
    """
    Deterministic mapping between an experimental trace and a synthetic trace.

    This is an *authority* object: it defines what will be compared and how.
    """
    name: str
    dtype: str  # e.g. "flux_loop", "pickup"
    exp: TraceSpec
    syn: TraceSpec
    units: Optional[str] = None
    notes: Optional[str] = None


def _as_path(base_dir: Path, p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else (base_dir / q).resolve()


def load_contracts(path: Path, base_dir: Optional[Path] = None) -> List[DiagnosticContract]:
    """
    Load diagnostic contracts JSON.

    Schema (versioned, minimal):
    {
      "version": "1.0",
      "diagnostics": [
        {
          "name": "...",
          "dtype": "flux_loop|pickup|...",
          "units": "Wb|T|...",
          "exp": {"csv": "inputs/..csv", "time_col": "time", "value_col": "...", "scale": 1.0, "sign": 1.0},
          "syn": {"csv": "synthetic/..csv", "time_col": "time", "value_col": "...", "scale": 1.0, "sign": 1.0}
        }
      ]
    }
    """
    obj = json.loads(path.read_text())
    base = (base_dir or path.parent).resolve()
    if not isinstance(obj, dict):
        raise ContractError("contracts JSON root must be an object")

    diags = obj.get("diagnostics", [])
    if not isinstance(diags, list):
        raise ContractError("'diagnostics' must be a list")

    out: List[DiagnosticContract] = []
    for i, d in enumerate(diags):
        if not isinstance(d, dict):
            raise ContractError(f"diagnostics[{i}] must be an object")
        name = str(d.get("name", "")).strip()
        if not name:
            raise ContractError(f"diagnostics[{i}].name missing/empty")
        dtype = str(d.get("dtype", "")).strip()
        if not dtype:
            raise ContractError(f"diagnostics[{i}].dtype missing/empty")

        exp = d.get("exp")
        syn = d.get("syn")
        if not isinstance(exp, dict) or not isinstance(syn, dict):
            raise ContractError(f"diagnostics[{i}] must contain 'exp' and 'syn' objects")

        exp_ts = TraceSpec(
            csv=_as_path(base, str(exp.get("csv", ""))),
            time_col=str(exp.get("time_col", "time")),
            value_col=str(exp.get("value_col", "")),
            scale=float(exp.get("scale", 1.0)),
            sign=float(exp.get("sign", 1.0)),
        )
        syn_ts = TraceSpec(
            csv=_as_path(base, str(syn.get("csv", ""))),
            time_col=str(syn.get("time_col", "time")),
            value_col=str(syn.get("value_col", "")),
            scale=float(syn.get("scale", 1.0)),
            sign=float(syn.get("sign", 1.0)),
        )
        if not exp_ts.value_col:
            raise ContractError(f"diagnostics[{i}].exp.value_col missing/empty")
        if not syn_ts.value_col:
            raise ContractError(f"diagnostics[{i}].syn.value_col missing/empty")

        out.append(DiagnosticContract(
            name=name,
            dtype=dtype,
            exp=exp_ts,
            syn=syn_ts,
            units=(str(d["units"]) if d.get("units") is not None else None),
            notes=(str(d["notes"]) if d.get("notes") is not None else None),
        ))
    return out


def validate_contracts(contracts: List[DiagnosticContract], require_files: bool = True) -> Dict[str, Any]:
    """
    Validate contracts deterministically. Returns a report dict.
    """
    report: Dict[str, Any] = {"ok": True, "errors": [], "n": len(contracts)}
    seen = set()
    for c in contracts:
        if c.name in seen:
            report["ok"] = False
            report["errors"].append(f"duplicate contract name: {c.name}")
        seen.add(c.name)

        for side, ts in [("exp", c.exp), ("syn", c.syn)]:
            if require_files and not ts.csv.exists():
                report["ok"] = False
                report["errors"].append(f"{c.name}: {side}.csv not found: {ts.csv}")
            if ts.sign not in (-1.0, 1.0):
                report["ok"] = False
                report["errors"].append(f"{c.name}: {side}.sign must be +1 or -1 (got {ts.sign})")
    return report


def write_resolved_contracts(run_dir: Path, contracts: List[DiagnosticContract]) -> Path:
    """
    Write a resolved, fully-absolute contract file into run_dir/contracts.
    """
    out_dir = run_dir / "contracts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "diagnostic_contracts.resolved.json"
    obj = {
        "version": "1.0",
        "diagnostics": [
            {
                "name": c.name,
                "dtype": c.dtype,
                "units": c.units,
                "notes": c.notes,
                "exp": {
                    "csv": str(c.exp.csv),
                    "time_col": c.exp.time_col,
                    "value_col": c.exp.value_col,
                    "scale": c.exp.scale,
                    "sign": c.exp.sign,
                },
                "syn": {
                    "csv": str(c.syn.csv),
                    "time_col": c.syn.time_col,
                    "value_col": c.syn.value_col,
                    "scale": c.syn.scale,
                    "sign": c.syn.sign,
                },
            } for c in contracts
        ],
    }
    out_path.write_text(json.dumps(obj, indent=2, sort_keys=True))
    return out_path


def resolve_contracts_for_run(contracts_path: Path, run_dir: Path) -> List[DiagnosticContract]:
    """Load contracts with paths resolved relative to the run directory (shot-scoped)."""
    return load_contracts(contracts_path, base_dir=Path(run_dir).resolve())
