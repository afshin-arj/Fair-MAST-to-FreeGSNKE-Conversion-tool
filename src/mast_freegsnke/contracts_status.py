"""Honest, single-line status for contract residual metrics.

Contract metrics compare experimental probe traces against synthetic probe
traces produced by the FreeGSNKE run. As of v10.2.0 neither side exists for
MAST shots in this repository:

- The extractor exports only 1-D magnetics variables; FAIR-MAST Level-2
  per-probe traces (e.g. flux_loop_flux) are 2-D (channel, time) and are not
  yet extracted into named columns.
- The generated FreeGSNKE inverse/forward runners do not emit synthetic probe
  CSVs under SHOTS/<N>/synthetic/.

Until both sides exist with verifiable shared channel identity (same probe
names, SI units, identity sign/scale), no diagnostic contracts authority is
shipped and metrics stay disabled. We never fabricate scale factors.

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
            "(see configs/diagnostic_contracts.example.json) and set diagnostic_contracts_path."
        )
    return (
        "[INFO] Contract residual metrics disabled: no diagnostic-contracts authority exists yet "
        "(experimental per-probe traces are not extracted and FreeGSNKE runs emit no synthetic probe CSVs); "
        "to enable, provide diagnostic_contracts_path + enable_contract_metrics=true once both sides exist "
        "(see HOW_TO_RUN.txt, 'Diagnostic contract metrics')."
    )
