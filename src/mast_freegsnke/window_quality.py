from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import math

try:
    import pandas as pd
    import numpy as np
except Exception:  # pragma: no cover
    pd = None  # type: ignore
    np = None  # type: ignore

from .windowing import TimeWindow, _find_time_column, _is_ip_source, _pick_ip_column

# Deterministic QC source preference: dedicated Ip export first, then the
# current extract output, then legacy names, then PF fallbacks.
QC_SOURCE_FILES = [
    "ip.csv",
    "magnetics_timeseries.csv",
    "magnetics_raw.csv",
    "magnetics.csv",
    "pf_active_raw.csv",
    "pf_currents.csv",
]


@dataclass(frozen=True)
class WindowDiagnostics:
    t_start: float
    t_end: float
    duration_s: float
    source: str
    signal_column: Optional[str]
    threshold: Optional[float]
    max_abs: Optional[float]
    mean_abs: Optional[float]
    frac_above_threshold: Optional[float]
    dsignal_max_abs: Optional[float]
    confidence: float
    flags: List[str]


def _require_stack() -> None:
    if pd is None or np is None:
        raise RuntimeError("pandas+numpy required for window quality. Install: pip install -e '.[zarr]'")


def _finite(x: float) -> bool:
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def _diff_max_abs(t: List[float], y: List[float]) -> Optional[float]:
    if len(t) < 3:
        return None
    tt = np.asarray(t, dtype=float)
    yy = np.asarray(y, dtype=float)
    dt = np.diff(tt)
    dy = np.diff(yy)
    good = dt != 0
    if not np.any(good):
        return None
    dydt = np.zeros_like(dy)
    dydt[good] = dy[good] / dt[good]
    return float(np.nanmax(np.abs(dydt)))


def _extract_signal(inputs_dir: Path, preferred_file: str) -> Tuple[str, str, List[float], List[float]]:
    path = inputs_dir / preferred_file
    if not path.exists():
        raise FileNotFoundError(str(path))
    df = pd.read_csv(path)
    if df.shape[0] < 3 or df.shape[1] < 2:
        raise ValueError(f"insufficient data in {preferred_file}")
    tcol = _find_time_column(list(df.columns))
    cols = [c for c in df.columns if c != tcol]
    if not cols:
        raise ValueError(f"no signals in {preferred_file}")
    # pick Ip-like if this source can carry a plasma-current signal
    sig = _pick_ip_column(cols) if _is_ip_source(preferred_file) else None
    if sig is None:
        # fallback: choose largest dynamic range in abs
        best_c = None
        best_span = -1.0
        for c in cols:
            try:
                y = df[c].astype(float).to_numpy()
                span = float(np.nanmax(np.abs(y)) - np.nanmin(np.abs(y)))
                if span > best_span:
                    best_span = span
                    best_c = c
            except Exception:
                continue
        sig = best_c or cols[0]
    t = df[tcol].astype(float).to_list()
    y = df[sig].astype(float).to_list()
    return preferred_file, sig, t, y


def evaluate_time_window(inputs_dir: Path, tw: TimeWindow) -> WindowDiagnostics:
    """Compute QC diagnostics and a conservative confidence score in [0,1].

    Confidence is heuristic:
      - penalize short duration
      - penalize narrow fraction above threshold (too spiky)
      - penalize missing threshold / signal
      - bonus if cross-check agrees with alternative signal window overlap
    """
    _require_stack()

    t0, t1 = float(tw.t_start), float(tw.t_end)
    dur = max(0.0, t1 - t0)

    flags: List[str] = []
    base = 0.8

    if dur <= 0:
        base = 0.0
        flags.append("non_positive_duration")

    if dur < 0.02:
        base -= 0.4
        flags.append("very_short_window")
    elif dur < 0.05:
        base -= 0.2
        flags.append("short_window")

    max_abs = None
    mean_abs = None
    frac = None
    dmax = None

    if tw.signal_column is None:
        base -= 0.15
        flags.append("missing_signal_column")

    # compute on the source file if possible
    try:
        file_label = tw.source
        # Use the window's source file when it is a known input CSV; otherwise
        # (e.g. source="override" or "consensus:*") fall back to the first
        # existing QC source in deterministic preference order.
        if file_label in QC_SOURCE_FILES and (inputs_dir / file_label).exists():
            preferred = file_label
        else:
            preferred = next(
                (f for f in QC_SOURCE_FILES if (inputs_dir / f).exists()),
                QC_SOURCE_FILES[0],
            )
        fname, sig, t, y = _extract_signal(inputs_dir, preferred)
        # window mask
        tt = np.asarray(t, dtype=float)
        yy = np.asarray(y, dtype=float)
        m = (tt >= t0) & (tt <= t1)
        if not np.any(m):
            base -= 0.25
            flags.append("no_samples_in_window")
        else:
            yw = yy[m]
            max_abs = float(np.nanmax(np.abs(yw)))
            mean_abs = float(np.nanmean(np.abs(yw)))
            if tw.threshold is not None and _finite(float(tw.threshold)):
                thr = float(tw.threshold)
                frac = float(np.nanmean((np.abs(yw) >= thr).astype(float)))
                if frac < 0.2:
                    base -= 0.25
                    flags.append("low_frac_above_threshold")
                elif frac < 0.4:
                    base -= 0.10
                    flags.append("moderate_frac_above_threshold")
            else:
                base -= 0.10
                flags.append("missing_threshold")
            dmax = _diff_max_abs(t, y)
    except Exception as e:
        base -= 0.20
        flags.append(f"qc_source_read_error:{e}")

    # Cross-check: compare inferred window using an alternate file
    try:
        alt_files = QC_SOURCE_FILES
        # pick an alternative different from source if possible
        src_file = tw.source
        src_guess = src_file if src_file in alt_files else None
        alt = None
        for f in alt_files:
            if f != src_guess and (inputs_dir / f).exists():
                alt = f
                break
        if alt is not None:
            _, _, t_alt, y_alt = _extract_signal(inputs_dir, alt)
            # infer alt window with same formed_frac if threshold known
            # compute max abs overall and threshold = formed_frac * max
            ya = np.asarray(y_alt, dtype=float)
            ta = np.asarray(t_alt, dtype=float)
            ymax = float(np.nanmax(np.abs(ya)))
            formed_frac = 0.8
            if tw.threshold is not None and max_abs is not None and max_abs > 0:
                # approximate formed_frac from threshold vs overall max in the original signal
                # keep bounded
                formed_frac = float(max(0.1, min(0.95, float(tw.threshold) / max_abs)))  # heuristic
            thr_alt = formed_frac * ymax
            idx = np.where(np.abs(ya) >= thr_alt)[0]
            if idx.size >= 2:
                a0, a1 = float(ta[int(idx[0])]), float(ta[int(idx[-1])])
                # overlap fraction relative to smaller duration
                ov0, ov1 = max(t0, a0), min(t1, a1)
                ov = max(0.0, ov1 - ov0)
                denom = max(1e-9, min(dur, max(0.0, a1 - a0)))
                overlap_frac = ov / denom
                if overlap_frac >= 0.7:
                    base += 0.10
                    flags.append("crosscheck_good_overlap")
                elif overlap_frac < 0.3:
                    base -= 0.15
                    flags.append("crosscheck_poor_overlap")
            else:
                flags.append("crosscheck_no_alt_window")
    except Exception as e:
        flags.append(f"crosscheck_error:{e}")

    conf = float(max(0.0, min(1.0, base)))
    return WindowDiagnostics(
        t_start=t0,
        t_end=t1,
        duration_s=dur,
        source=tw.source,
        signal_column=tw.signal_column,
        threshold=tw.threshold,
        max_abs=max_abs,
        mean_abs=mean_abs,
        frac_above_threshold=frac,
        dsignal_max_abs=dmax,
        confidence=conf,
        flags=flags,
    )


def format_diagnostics(diag: WindowDiagnostics) -> str:
    lines = []
    lines.append("WINDOW QC REPORT")
    lines.append("================")
    lines.append(f"t_start: {diag.t_start}")
    lines.append(f"t_end  : {diag.t_end}")
    lines.append(f"duration_s: {diag.duration_s}")
    lines.append(f"source: {diag.source}")
    lines.append(f"signal_column: {diag.signal_column}")
    lines.append(f"threshold: {diag.threshold}")
    lines.append(f"max_abs: {diag.max_abs}")
    lines.append(f"mean_abs: {diag.mean_abs}")
    lines.append(f"frac_above_threshold: {diag.frac_above_threshold}")
    lines.append(f"dsignal_max_abs: {diag.dsignal_max_abs}")
    lines.append(f"confidence: {diag.confidence}")
    lines.append("flags:")
    for f in diag.flags:
        lines.append(f"  - {f}")
    return "\n".join(lines) + "\n"
