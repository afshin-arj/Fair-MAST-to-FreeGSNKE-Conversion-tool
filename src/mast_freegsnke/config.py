from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

@dataclass(frozen=True)
class AppConfig:
    mastapp_base_url: str
    required_groups: List[str]
    level2_s3_prefix: str
    s5cmd_path: str
    runs_dir: Path
    cache_dir: Path
    formed_plasma_frac: float
    s3_layout_patterns: List[str]
    allow_missing_geometry: bool

    # Optional: execute FreeGSNKE scripts after generating a run folder.
    execute_freegsnke: bool
    # one of: none | inverse | forward | both
    freegsnke_run_mode: str
    # Optional python interpreter path for FreeGSNKE environment; defaults to current interpreter.
    freegsnke_python: Optional[str]

    # Optional residual comparison configuration.
    # Each entry is a dict contract that describes how to compare experimental vs synthetic traces.
    diagnostics_compare: List[Dict[str, Any]]

    # Optional: path to diagnostic contracts authority JSON.
    diagnostic_contracts_path: Optional[str]
    # Optional: path to PF/coil mapping authority JSON.
    coil_map_path: Optional[str]
    # Enable contract-driven extraction + residual metrics (requires contracts).
    enable_contract_metrics: bool

    # Optional: machine authority directory (versioned geometry/registry).
    machine_authority_dir: Optional[str]
    # If True, missing/invalid machine authority is a blocking error.
    require_machine_authority: bool
    # If True, also hash downloaded data cache tree (can be expensive).
    provenance_hash_data: bool


    @staticmethod
    def load(path: Path) -> "AppConfig":
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        text = path.read_text(encoding="utf-8")
        suf = path.suffix.lower()
        if suf in (".yaml", ".yml"):
            if yaml is None:
                raise RuntimeError("YAML config requested but PyYAML is not installed. Use JSON or install pyyaml.")
            obj = yaml.safe_load(text) or {}
        else:
            obj = json.loads(text)

        # Normalize + defaults
        mastapp_base_url = str(obj.get("mastapp_base_url", "https://mastapp.site/json")).rstrip("/")
        required_groups = list(obj.get("required_groups", ["pf_active", "magnetics"]))
        level2_s3_prefix = str(obj.get("level2_s3_prefix", ""))
        s5cmd_path = str(obj.get("s5cmd_path", "s5cmd"))
        runs_dir = Path(obj.get("runs_dir", "runs"))
        cache_dir = Path(obj.get("cache_dir", "data_cache"))
        formed_plasma_frac = float(obj.get("formed_plasma_frac", 0.80))
        allow_missing_geometry = bool(obj.get("allow_missing_geometry", False))

        execute_freegsnke = bool(obj.get("execute_freegsnke", False))
        freegsnke_run_mode = str(obj.get("freegsnke_run_mode", "none")).lower()
        freegsnke_python = (str(obj["freegsnke_python"]) if obj.get("freegsnke_python") else None)

        diagnostics_compare = list(obj.get("diagnostics_compare", []))
        diagnostic_contracts_path = (str(obj["diagnostic_contracts_path"]) if obj.get("diagnostic_contracts_path") else None)
        coil_map_path = (str(obj["coil_map_path"]) if obj.get("coil_map_path") else None)
        enable_contract_metrics = bool(obj.get("enable_contract_metrics", False))

        machine_authority_dir = (str(obj["machine_authority_dir"]) if obj.get("machine_authority_dir") else None)
        require_machine_authority = bool(obj.get("require_machine_authority", False))
        provenance_hash_data = bool(obj.get("provenance_hash_data", False))

        s3_layout_patterns = list(obj.get("s3_layout_patterns", [
            "{prefix}/{group}/shot_{shot}.zarr",
            "{prefix}/shot_{shot}/{group}.zarr",
            "{prefix}/shot_{shot}_{group}.zarr",
        ]))

        return AppConfig(
            mastapp_base_url=mastapp_base_url,
            required_groups=required_groups,
            level2_s3_prefix=level2_s3_prefix,
            s5cmd_path=s5cmd_path,
            runs_dir=runs_dir,
            cache_dir=cache_dir,
            formed_plasma_frac=formed_plasma_frac,
            s3_layout_patterns=s3_layout_patterns,
            allow_missing_geometry=allow_missing_geometry,
            execute_freegsnke=execute_freegsnke,
            freegsnke_run_mode=freegsnke_run_mode,
            freegsnke_python=freegsnke_python,
            diagnostics_compare=diagnostics_compare,
            diagnostic_contracts_path=diagnostic_contracts_path,
            coil_map_path=coil_map_path,
            enable_contract_metrics=enable_contract_metrics,
            machine_authority_dir=machine_authority_dir,
            require_machine_authority=require_machine_authority,
            provenance_hash_data=provenance_hash_data,
        )
