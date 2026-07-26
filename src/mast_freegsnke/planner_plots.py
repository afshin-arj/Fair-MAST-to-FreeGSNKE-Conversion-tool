"""Planner static plots: per-circuit small-multiples + cited limit bands."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .coil_limits import CoilLimitsAuthority


def _grid_shape(n: int) -> Tuple[int, int]:
    if n <= 0:
        return 1, 1
    if n <= 3:
        return 1, n
    if n <= 6:
        return 2, 3
    if n <= 8:
        return 2, 4
    cols = int(np.ceil(np.sqrt(n)))
    rows = int(np.ceil(n / cols))
    return rows, cols


def _shade_limits(ax: Any, lo: float, hi: float, *, color: str = "0.75") -> None:
    if not (np.isfinite(lo) and np.isfinite(hi) and lo < hi):
        return
    ax.axhspan(lo, hi, color=color, alpha=0.18, zorder=0)
    ax.axhline(lo, color=color, lw=0.8, ls=":", alpha=0.8)
    ax.axhline(hi, color=color, lw=0.8, ls=":", alpha=0.8)


def _drive_tag(label: Optional[str]) -> str:
    s = str(label or "").strip()
    if s == "ohmic_synthetic_IxR":
        return "obs: ohmic I×R"
    if s == "measured_fairmast_V":
        return "obs: measured V"
    if s and s != "unknown":
        return f"obs: {s}"
    return "obs"


def write_planner_iv_plots(
    out_dir: Path,
    *,
    times: np.ndarray,
    circuit_order: Sequence[str],
    I_plan: np.ndarray,
    I_meas: np.ndarray,
    V_plan: np.ndarray,
    V_obs: np.ndarray,
    coil_limits: CoilLimitsAuthority,
    drive_labels: Optional[Mapping[str, str]] = None,
    dpi: int = 120,
) -> List[str]:
    """Write small-multiple I/V (+ Δ) PNGs. Returns basenames written (or skip tokens)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    order = [str(c) for c in circuit_order]
    t = np.asarray(times, dtype=float).ravel()
    Ip = np.asarray(I_plan, dtype=float)
    Im = np.asarray(I_meas, dtype=float)
    Vp = np.asarray(V_plan, dtype=float)
    Vo = np.asarray(V_obs, dtype=float)
    n = len(order)
    if Ip.shape != (t.size, n) or Im.shape != Ip.shape or Vp.shape != Ip.shape or Vo.shape != Ip.shape:
        raise ValueError("I/V arrays must be shape (n_times, n_circuits)")

    drive_labels = dict(drive_labels or {})
    policy = (coil_limits.resolution or {}).get("policy") or coil_limits.limit_policy
    margin = coil_limits.margin_factor
    limit_caption = (
        f"bands = cited I/V bounds"
        + (f" (policy={policy}" + (f", margin={margin:g}" if margin else "") + ")" if policy else "")
    )

    written: List[str] = []
    rows, cols = _grid_shape(n)

    def _signal_fig(
        *,
        y_plan: np.ndarray,
        y_ref: np.ndarray,
        ylabel: str,
        title: str,
        filename: str,
        kind: str,
    ) -> None:
        fig, axs = plt.subplots(rows, cols, figsize=(3.2 * cols, 2.4 * rows), dpi=dpi, sharex=True)
        flat = np.atleast_1d(axs).ravel()
        for i, name in enumerate(order):
            ax = flat[i]
            lim = coil_limits.circuits.get(name)
            if lim is not None:
                if kind == "I":
                    lo, hi = lim.i_bounds()
                else:
                    lo, hi = lim.v_bounds()
                _shade_limits(ax, lo, hi)
            ax.plot(t, y_plan[:, i], color="C0", lw=1.4, label="plan")
            tag = _drive_tag(drive_labels.get(name)) if kind == "V" else "meas"
            ls = "--"
            color = "C3" if (kind == "V" and drive_labels.get(name) == "ohmic_synthetic_IxR") else "0.35"
            ax.plot(t, y_ref[:, i], color=color, ls=ls, lw=1.2, alpha=0.9, label=tag)
            ax.set_title(name, fontsize=9)
            ax.grid(True, alpha=0.3)
            ax.tick_params(labelsize=7)
            if i == 0:
                ax.legend(fontsize=6, loc="best")
            if kind == "V" and drive_labels.get(name) == "ohmic_synthetic_IxR":
                ax.text(
                    0.02,
                    0.95,
                    "ohmic I×R",
                    transform=ax.transAxes,
                    fontsize=7,
                    va="top",
                    color="C3",
                )
        for j in range(n, len(flat)):
            flat[j].set_visible(False)
        for ax in flat[max(0, n - cols) : n]:
            ax.set_xlabel("t [s]", fontsize=8)
        flat[0].set_ylabel(ylabel, fontsize=8)
        fig.suptitle(f"{title}\n{limit_caption}", fontsize=10)
        fig.tight_layout(rect=(0, 0, 1, 0.94))
        path = out_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        written.append(path.name)

    def _delta_fig(
        *,
        y_plan: np.ndarray,
        y_ref: np.ndarray,
        ylabel: str,
        title: str,
        filename: str,
    ) -> None:
        fig, axs = plt.subplots(rows, cols, figsize=(3.2 * cols, 2.4 * rows), dpi=dpi, sharex=True)
        flat = np.atleast_1d(axs).ravel()
        for i, name in enumerate(order):
            ax = flat[i]
            d = y_plan[:, i] - y_ref[:, i]
            ax.axhline(0.0, color="0.5", lw=0.8)
            ax.plot(t, d, color="C0", lw=1.2)
            ax.set_title(name, fontsize=9)
            ax.grid(True, alpha=0.3)
            ax.tick_params(labelsize=7)
        for j in range(n, len(flat)):
            flat[j].set_visible(False)
        for ax in flat[max(0, n - cols) : n]:
            ax.set_xlabel("t [s]", fontsize=8)
        flat[0].set_ylabel(ylabel, fontsize=8)
        fig.suptitle(title, fontsize=10)
        fig.tight_layout(rect=(0, 0, 1, 0.95))
        path = out_dir / filename
        fig.savefig(path, bbox_inches="tight")
        plt.close(fig)
        written.append(path.name)

    _signal_fig(
        y_plan=Ip,
        y_ref=Im,
        ylabel="I [A]",
        title="Planner: planned vs measured currents (per circuit)",
        filename="planning_current_by_circuit.png",
        kind="I",
    )
    _delta_fig(
        y_plan=Ip,
        y_ref=Im,
        ylabel="ΔI plan−meas [A]",
        title="Planner: current residual ΔI (per circuit)",
        filename="planning_current_delta.png",
    )
    _signal_fig(
        y_plan=Vp,
        y_ref=Vo,
        ylabel="V [V]",
        title="Planner: planned vs observed voltages (per circuit)",
        filename="planning_voltage_by_circuit.png",
        kind="V",
    )
    _delta_fig(
        y_plan=Vp,
        y_ref=Vo,
        ylabel="ΔV plan−obs [V]",
        title="Planner: voltage residual ΔV (per circuit)",
        filename="planning_voltage_delta.png",
    )
    return written
