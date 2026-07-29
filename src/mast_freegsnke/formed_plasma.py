"""Formed-plasma time selection shared by inverse scripts and boundary remap."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple


def estimate_formed_plasma_time(
    ip_csv: Path,
    *,
    frac: float = 0.80,
) -> Tuple[float, float, float]:
    """Pick formed-plasma ``t`` from ``ip.csv`` (same rule as ``inverse_run``).

    Among samples with ``Ip >= frac * Ip_max`` (positive Ip only), choose the
    time of minimum ``|dIp/dt|``. Returns ``(t_s, Ip_at_t, Ip_max)``.
    """
    import numpy as np
    import pandas as pd

    path = Path(ip_csv)
    if not path.is_file():
        raise FileNotFoundError(f"missing ip.csv: {path}")
    df = pd.read_csv(path)
    if "time" not in df.columns or "ip" not in df.columns:
        raise ValueError(f"ip.csv must have time,ip columns: {path}")
    t = df["time"].to_numpy(dtype=float)
    ip = df["ip"].to_numpy(dtype=float)
    mask_pos = ip > 0
    t = t[mask_pos]
    ip = ip[mask_pos]
    if t.size < 3:
        raise RuntimeError("ip.csv has too few positive-Ip samples for formed-plasma pick")
    ip_max = float(np.max(ip))
    mask = ip >= float(frac) * ip_max
    if not np.any(mask):
        raise RuntimeError(
            "Could not find formed plasma time. Lower formed_plasma_frac."
        )
    t_sel = t[mask]
    ip_sel = ip[mask]
    dip_dt = np.gradient(ip_sel, t_sel)
    idx = int(np.argmin(np.abs(dip_dt)))
    return float(t_sel[idx]), float(ip_sel[idx]), ip_max


def estimate_formed_plasma_t_or_none(
    ip_csv: Path,
    *,
    frac: float = 0.80,
) -> Optional[float]:
    try:
        t, _ip, _mx = estimate_formed_plasma_time(ip_csv, frac=frac)
        return float(t)
    except Exception:
        return None
