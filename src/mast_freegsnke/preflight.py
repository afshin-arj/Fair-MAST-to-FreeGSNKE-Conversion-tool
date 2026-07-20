"""Shared shot-only preflight checks (doctor + interactive launcher)."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from .config import AppConfig
from .freegsnke_runner import resolve_freegsnke_python
from .util import resolve_s5cmd_path


def _has(pkg: str) -> bool:
    return importlib.util.find_spec(pkg) is not None


def collect_happy_path_failures(cfg: AppConfig, cwd: Optional[Path] = None) -> List[str]:
    """Return human-readable failure strings for shot-only run readiness.

    Empty list means ready (or only non-blocking gaps). Used by interactive
    preflight; doctor prints richer OK/WARN lines but should FAIL on the same
    blocking conditions when execute_freegsnke is enabled.
    """
    cwd = cwd or Path.cwd()
    fails: List[str] = []

    s5 = resolve_s5cmd_path(cfg.s5cmd_path, cwd)
    if not Path(s5).is_file() and shutil.which(s5) is None:
        fails.append(
            "s5cmd not found. Run: python scripts/ensure_s5cmd.py "
            "(or re-run run_pipeline.cmd/.sh)"
        )

    need_extract = bool(cfg.execute_freegsnke or cfg.execute_evolutive)
    if need_extract:
        missing = [p for p in ("xarray", "pandas", "zarr", "numpy") if not _has(p)]
        if missing:
            fails.append(
                "missing Python packages required for FAIR-MAST extract: "
                f"{', '.join(missing)}. Install: pip install -e \".[zarr]\""
            )

    if cfg.require_machine_authority or cfg.execute_freegsnke:
        ma = Path(cfg.machine_authority_dir or "")
        if not ma.is_absolute():
            ma = (cwd / ma).resolve()
        if not ma.is_dir():
            fails.append(f"machine_authority_dir missing: {cfg.machine_authority_dir}")
        else:
            from .machine_authority import machine_authority_from_dir

            auth, rep = machine_authority_from_dir(ma)
            if auth is None:
                fails.append(f"machine authority invalid: {rep.get('errors')}")

    if cfg.coil_map_path:
        p = Path(cfg.coil_map_path)
        if not p.is_absolute():
            p = (cwd / p).resolve()
        if not p.is_file():
            fails.append(f"coil_map_path missing: {cfg.coil_map_path}")
        else:
            from .coil_map import load_coil_map, validate_coil_map

            rep = validate_coil_map(load_coil_map(p))
            if not rep.get("ok"):
                fails.append(f"coil_map invalid: {rep.get('errors')}")

    if cfg.voltage_map_path and (cfg.execute_evolutive or cfg.execute_freegsnke):
        p = Path(cfg.voltage_map_path)
        if not p.is_absolute():
            p = (cwd / p).resolve()
        if not p.is_file():
            fails.append(f"voltage_map_path missing: {cfg.voltage_map_path}")
        else:
            from .voltage_map import load_voltage_map, validate_voltage_map

            rep = validate_voltage_map(load_voltage_map(p))
            if not rep.get("ok"):
                fails.append(f"voltage_map invalid: {rep.get('errors')}")

    if cfg.execute_freegsnke:
        exe = resolve_freegsnke_python(cfg.freegsnke_python, cwd)
        fp = Path(exe)
        if cfg.freegsnke_python and not fp.exists():
            fails.append(
                f"freegsnke_python not found: {cfg.freegsnke_python}\n"
                "[HINT] python scripts/ensure_freegsnke_env.py"
            )
        else:
            try:
                chk = subprocess.run(
                    [exe, "-c", "import freegsnke"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except Exception as e:
                fails.append(f"freegsnke check failed for {exe}: {e}")
            else:
                if chk.returncode != 0:
                    fails.append(
                        f"freegsnke not importable in {exe}\n"
                        "[HINT] python scripts/ensure_freegsnke_env.py"
                    )

    if cfg.enable_contract_metrics and cfg.diagnostic_contracts_path:
        p = Path(cfg.diagnostic_contracts_path)
        if not p.is_absolute():
            p = (cwd / p).resolve()
        if not p.is_file():
            fails.append(f"diagnostic_contracts_path missing: {cfg.diagnostic_contracts_path}")
        else:
            from .diagnostic_contracts import load_contracts, validate_contracts

            try:
                contracts = load_contracts(p)
                rep = validate_contracts(contracts, require_files=False)
                if not rep.get("ok"):
                    fails.append(f"diagnostic_contracts invalid: {rep.get('errors')}")
            except Exception as e:
                fails.append(f"diagnostic_contracts load failed: {e}")

    return fails
