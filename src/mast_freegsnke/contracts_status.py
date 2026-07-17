"""Honest, single-line status for contract residual metrics.

As of v10.4.0 the shot-only happy path ships a real diagnostic contracts
authority (configs/diagnostic_contracts.json) and enables metrics by default:

- Extractor writes inputs/flux_loops.csv and inputs/pickups.csv with FAIR-MAST
  channel names verbatim (units from zarr attrs: Wb / T). Probe families on
  other timebases (mirnov/saddle/omaha) are extracted verbatim for audit under
  inputs/audit_other_timebase/ with evidence-based exclusion reasons.
- Inverse FreeGSNKE runner solves one inverse equilibrium at the formed-plasma
  t0 (for dump/plots/forward replay), then solves one forward-style Grad-
  Shafranov equilibrium per deterministic window sample time
  (metrics_timebase authority, rule linspace_window_inclusive, config key
  metrics_n_times; solve_mode=forward_gs_at_measured_pf_ip) and emits multi-row
  synthetic/synthetic_fluxloops.csv and synthetic/synthetic_pickups.csv via
  freegsnke.magnetic_probes.Probes (calculate_fluxloop_value /
  calculate_pickup_value), plus synthetic/synthetic_times.json.
- Metrics interpolate experimental traces onto the solved synthetic times and
  score RMS/MAE/max_abs across all sample times. ALL identity-mapped channels
  are contracted; channels that are all-NaN on the current shot are skipped
  shot-scoped (status skipped_all_nan), never fabricated. Real failures remain
  blocking when enable_contract_metrics=true.

Probe families on other timebases (mirnov/saddle/omaha) remain excluded from
the contracts authority on explicit Level-2 evidence (raw volts without
published calibration factors; self-contradictory unit metadata such as
units='T' vs label='Tesla/sec'/'mT'; no FreeGSNKE synthesizer for AC
fluctuation or saddle surface-flux measurements).

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
