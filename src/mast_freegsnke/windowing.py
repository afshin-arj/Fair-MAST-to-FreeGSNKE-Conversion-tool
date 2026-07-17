from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import math

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore


@dataclass(frozen=True)
class TimeWindow:
    t_start: float
    t_end: float
    source: str
    signal_column: Optional[str]
    threshold: Optional[float]
    note: Optional[str] = None


def _require_pandas() -> None:
    if pd is None:
        raise RuntimeError("pandas is required for time-window inference. Install optional deps: pip install -e '.[zarr]'")


def _find_time_column(cols: List[str]) -> str:
    # Be liberal: MastApp exports often use 'time' but allow other variants.
    cand = [c for c in cols if c.lower() in ("time", "t", "t[s]", "time_s", "time_sec", "seconds")]
    if cand:
        return cand[0]
    # fallback: first column that looks like time
    for c in cols:
        cl = c.lower()
        if "time" in cl and ("s" in cl or "sec" in cl):
            return c
    return cols[0]


def _is_ip_source(label: str) -> bool:
    """Labels whose columns may contain a plasma-current (Ip) signal."""
    return "magnetics" in label or label == "ip.csv"


def _pick_ip_column(cols: List[str]) -> Optional[str]:
    # Heuristic patterns for plasma current
    pats = [
        "ip", "i_p", "plasma_current", "plasma current", "i plasma", "current_plasma",
        "pcur", "plasma_i", "plasma-i",
    ]
    best = None
    for c in cols:
        cl = c.lower().replace("-", "_")
        if cl in ("time", "t"):
            continue
        for p in pats:
            if p.replace(" ", "_") in cl:
                best = c
                break
        if best:
            break
    return best


def _infer_window_from_signal(t: List[float], y: List[float], formed_frac: float) -> Tuple[float, float, float]:
    # Use abs(y). Threshold = formed_frac * max(abs(y)).
    ay = [abs(v) for v in y if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not ay:
        raise ValueError("signal is empty")
    ymax = max(ay)
    thr = formed_frac * ymax
    idx = [i for i, v in enumerate(y) if v is not None and not (isinstance(v, float) and math.isnan(v)) and abs(v) >= thr]
    if not idx:
        raise ValueError("no samples above threshold")
    i0, i1 = idx[0], idx[-1]
    return float(t[i0]), float(t[i1]), float(thr)


def infer_time_window(inputs_dir: Path, formed_frac: float) -> TimeWindow:
    """Infer a reasonable formed-plasma time window from extracted CSV inputs.

    Priority:
      1) ip.csv (dedicated plasma-current export from extract)
      2) magnetics_timeseries.csv / legacy magnetics_raw.csv / magnetics.csv with an Ip-like column
      3) pf_active_raw.csv (fallback: uses largest-magnitude column as proxy)
      4) fallback to full time extent of any available CSV
    """
    _require_pandas()

    candidates = [
        (inputs_dir / "ip.csv", "ip.csv"),
        (inputs_dir / "magnetics_timeseries.csv", "magnetics_timeseries.csv"),
        (inputs_dir / "magnetics_raw.csv", "magnetics_raw.csv"),
        (inputs_dir / "magnetics.csv", "magnetics.csv"),
        (inputs_dir / "pf_active_raw.csv", "pf_active_raw.csv"),
        (inputs_dir / "pf_currents.csv", "pf_currents.csv"),
    ]
    existing = [(p, label) for p, label in candidates if p.exists()]
    if not existing:
        raise FileNotFoundError(f"No input CSVs found in {inputs_dir}")

    # Try magnetics first using Ip
    for path, label in existing:
        df = pd.read_csv(path)
        if df.shape[0] < 3 or df.shape[1] < 2:
            continue
        tcol = _find_time_column(list(df.columns))
        cols = [c for c in df.columns if c != tcol]
        if not cols:
            continue

        ipcol = _pick_ip_column(cols) if _is_ip_source(label) else None
        if ipcol is not None:
            t = df[tcol].astype(float).to_list()
            y = df[ipcol].astype(float).to_list()
            try:
                t0, t1, thr = _infer_window_from_signal(t, y, formed_frac)
                return TimeWindow(t_start=t0, t_end=t1, source=label, signal_column=ipcol, threshold=thr)
            except Exception as e:
                # Continue trying other sources
                last_err = str(e)

    # Fallback: pick largest-dynamic-range column from first usable file
    for path, label in existing:
        df = pd.read_csv(path)
        if df.shape[0] < 3 or df.shape[1] < 2:
            continue
        tcol = _find_time_column(list(df.columns))
        cols = [c for c in df.columns if c != tcol]
        if not cols:
            continue
        # choose by max(abs)-min(abs)
        best_c = None
        best_span = -1.0
        for c in cols:
            try:
                y = df[c].astype(float)
                span = float(y.abs().max() - y.abs().min())
                if span > best_span:
                    best_span = span
                    best_c = c
            except Exception:
                continue
        if best_c is None:
            continue
        t = df[tcol].astype(float).to_list()
        y = df[best_c].astype(float).to_list()
        try:
            t0, t1, thr = _infer_window_from_signal(t, y, formed_frac)
            return TimeWindow(t_start=t0, t_end=t1, source=label, signal_column=best_c, threshold=thr, note="fallback_proxy_signal")
        except Exception:
            # fallback to full extent
            t0, t1 = float(min(t)), float(max(t))
            return TimeWindow(t_start=t0, t_end=t1, source=label, signal_column=best_c, threshold=None, note="fallback_full_extent")

    # last resort: full extent of first file
    path, label = existing[0]
    df = pd.read_csv(path)
    tcol = _find_time_column(list(df.columns))
    t = df[tcol].astype(float).to_list()
    return TimeWindow(t_start=float(min(t)), t_end=float(max(t)), source=label, signal_column=None, threshold=None, note="fallback_first_file")
