"""Honest, single-line status for contract residual metrics + calibration.

As of v10.6.0 the shot-only happy path ships:

- Real diagnostic contracts (configs/diagnostic_contracts.json) for shared-
  timebase flux loops + pickups; metrics enabled by default.
- Optional diagnostic calibration (configs/diagnostic_calibration.json) with
  empty channels / status=awaiting_authority so mirnov/saddle/omaha stay
  audit-only until explicit per-channel scale/sign/source is provided.
  Never invents V->T factors.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from .config import AppConfig
from .diagnostic_calibration import (
    CalibrationError,
    DiagnosticCalibration,
    calibration_status_line,
    load_diagnostic_calibration,
)


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


def _resolve_cal_path(cfg: AppConfig, cwd: Optional[Path] = None) -> Optional[Path]:
    raw = cfg.diagnostic_calibration_path
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = ((cwd or Path.cwd()) / p).resolve()
    return p


def load_calibration_for_config(
    cfg: AppConfig, *, cwd: Optional[Path] = None
) -> Tuple[Optional[DiagnosticCalibration], Optional[str]]:
    """Load calibration if configured. Returns (cal, error_message)."""
    path = _resolve_cal_path(cfg, cwd=cwd)
    if path is None:
        return None, None
    try:
        return load_diagnostic_calibration(path), None
    except CalibrationError as e:
        return None, str(e)


def diagnostic_calibration_status_line(
    cfg: AppConfig,
    *,
    cwd: Optional[Path] = None,
    apply_report: Optional[dict] = None,
) -> str:
    """Always-on banner for mirnov/saddle/omaha calibration state."""
    path = cfg.diagnostic_calibration_path
    cal, err = load_calibration_for_config(cfg, cwd=cwd)
    if path and err:
        return f"[FAIL] diagnostic_calibration invalid ({path}): {err}"
    return calibration_status_line(path=path, cal=cal, apply_report=apply_report)


def status_lines_for_run(cfg: AppConfig, *, cwd: Optional[Path] = None) -> list[str]:
    """Lines to print for interactive / CLI run banners."""
    lines: list[str] = []
    cm = contract_metrics_status_line(cfg)
    if cm:
        lines.append(cm)
    lines.append(diagnostic_calibration_status_line(cfg, cwd=cwd))
    return lines
