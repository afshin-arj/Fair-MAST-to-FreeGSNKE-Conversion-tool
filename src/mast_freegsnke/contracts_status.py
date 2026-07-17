"""Honest, single-line status for contract residual metrics.

As of v10.3.0 the shot-only happy path ships a real diagnostic contracts
authority (configs/diagnostic_contracts.json) and enables metrics by default:

- Extractor writes inputs/flux_loops.csv and inputs/pickups.csv with FAIR-MAST
  channel names verbatim (units from zarr attrs: Wb / T).
- Inverse FreeGSNKE runner emits synthetic/synthetic_fluxloops.csv and
  synthetic/synthetic_pickups.csv via freegsnke.magnetic_probes.Probes
  (calculate_fluxloop_value / calculate_pickup_value).
- Metrics interpolate experimental traces onto the solved synthetic time
  slice(s); failures remain blocking when enable_contract_metrics=true.

Probe families on other timebases (mirnov/saddle/omaha) or without unit-matched
identity remain excluded from the contracts authority.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

from typing import Optional

from .config import AppConfig


def contract_metrics_status_line(cfg: AppConfig) -> Optional[str]:
    """One clear line explaining why contract metrics are off, or None when enabled and wired."""
    if cfg.enable_contract_metrics and cfg.diagnostic_contracts_path:
        return None
    if cfg.enable_contract_metrics and not cfg.diagnostic_contracts_path:
        return (
            "[WARN] enable_contract_metrics=true but diagnostic_contracts_path is not set: "
            "metrics will be skipped. Provide a diagnostic contracts JSON "
            "(see configs/diagnostic_contracts.json) and set diagnostic_contracts_path."
        )
    return (
        "[INFO] Contract residual metrics disabled in this config "
        "(set diagnostic_contracts_path + enable_contract_metrics=true to score "
        "experimental vs synthetic probes; see HOW_TO_RUN.txt, 'Diagnostic contract metrics')."
    )
