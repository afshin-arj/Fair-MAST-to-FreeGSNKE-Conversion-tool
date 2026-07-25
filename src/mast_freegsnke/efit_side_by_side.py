"""Classic MAST FreeGSNKE | EFIT++ archive side-by-side animation (ADR-002).

Inspired by FreeGSNKE's MAST-U forward-vs-EFIT demo, but for classic MAST using
FAIR-MAST Level-2 ``equilibrium`` (archived EFIT++) and FreeGSNKE LCFS products —
never invents geometry or live EFIT++.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _HAS_MPL = True
except Exception:  # pragma: no cover
    _HAS_MPL = False


def _load_window(run_dir: Path) -> Tuple[Optional[float], Optional[float]]:
    for rel in ("inputs/window.json", "window.json", "01_summary/SUMMARY.json"):
        p = Path(run_dir) / rel
        if not p.is_file():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        w = obj.get("window") if isinstance(obj.get("window"), dict) else obj
        try:
            t0 = float(w["t_start"]) if w.get("t_start") is not None else None
            t1 = float(w["t_end"]) if w.get("t_end") is not None else None
            return t0, t1
        except (TypeError, ValueError, KeyError):
            continue
    return None, None


def _freegsnke_lcfs_timeseries(run_dir: Path) -> List[Dict[str, Any]]:
    """Load multi-time FreeGSNKE LCFS when present; else single static LCFS."""
    from .freegsnke_lcfs import (
        freegsnke_lcfs_timeseries_candidates,
        lcfs_from_dump_dict,
        load_inverse_dump,
        read_lcfs_csv,
        freegsnke_lcfs_csv_candidates,
    )

    out: List[Dict[str, Any]] = []
    for p in freegsnke_lcfs_timeseries_candidates(Path(run_dir)):
        if not p.is_file():
            continue
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        cols = {c.lower(): c for c in df.columns}
        if "time" not in cols or "r" not in cols or "z" not in cols:
            continue
        for t, g in df.groupby(cols["time"]):
            rr = g[cols["r"]].to_numpy(dtype=float)
            zz = g[cols["z"]].to_numpy(dtype=float)
            m = np.isfinite(rr) & np.isfinite(zz)
            if int(m.sum()) >= 3:
                out.append(
                    {
                        "t": float(t),
                        "R": rr[m],
                        "Z": zz[m],
                        "source": str(p.as_posix()),
                    }
                )
        if out:
            return out

    for p in freegsnke_lcfs_csv_candidates(Path(run_dir)):
        if not p.is_file():
            continue
        got = read_lcfs_csv(p)
        if got is None:
            continue
        t_static: Optional[float] = None
        try:
            df = pd.read_csv(p)
            cols = {c.lower(): c for c in df.columns}
            if "time" in cols:
                tt = df[cols["time"]].to_numpy(dtype=float)
                finite = tt[np.isfinite(tt)]
                if finite.size:
                    t_static = float(finite[0])
        except Exception:
            t_static = None
        out.append(
            {
                "t": t_static,
                "R": got[0],
                "Z": got[1],
                "source": str(p.as_posix()),
            }
        )
        return out

    dump = load_inverse_dump(Path(run_dir))
    if dump is not None:
        fg = lcfs_from_dump_dict(dump)
        if fg is not None:
            t0 = dump.get("t0")
            try:
                t_val = float(t0) if t0 is not None else None
            except (TypeError, ValueError):
                t_val = None
            out.append(
                {
                    "t": t_val,
                    "R": fg[0],
                    "Z": fg[1],
                    "source": "inverse_dump.lcfs_R/Z",
                }
            )
            return out

    # Legacy: eq object inside dump (rare) / CSV-less scorecard path
    from .efit_compare import _try_freegsnke_products

    fg2, _ = _try_freegsnke_products(Path(run_dir))
    if fg2 is not None:
        out.append(
            {
                "t": None,
                "R": fg2[0],
                "Z": fg2[1],
                "source": "static_freegsnke_lcfs",
            }
        )
    return out


def _nearest_fg(
    series: Sequence[Dict[str, Any]], t: float
) -> Optional[Dict[str, Any]]:
    if not series:
        return None
    timed = [s for s in series if s.get("t") is not None]
    if not timed:
        return series[0]
    best = min(timed, key=lambda s: abs(float(s["t"]) - float(t)))
    return best


def _load_pf_currents_panel(
    run_dir: Path, t: float
) -> Optional[Dict[str, float]]:
    """Measured PF currents nearest to t (for footer strip)."""
    for rel in ("inputs/pf_currents.csv", "02_measured_data/02_pf/pf_currents.csv"):
        p = Path(run_dir) / rel
        if not p.is_file():
            continue
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        cols = {c.lower(): c for c in df.columns}
        if "time" not in cols:
            continue
        tt = df[cols["time"]].to_numpy(dtype=float)
        if not np.isfinite(tt).any():
            continue
        i = int(np.nanargmin(np.abs(tt - float(t))))
        row: Dict[str, float] = {}
        for c in df.columns:
            if str(c).lower() == "time":
                continue
            try:
                v = float(df[c].iloc[i])
            except (TypeError, ValueError):
                continue
            if np.isfinite(v):
                row[str(c)] = v
        return row or None
    return None


def _draw_colored_psi(
    ax: Any,
    psi: np.ndarray,
    r_c: Any,
    z_c: Any,
    *,
    cmap: str,
    n_levels: int = 24,
) -> bool:
    """Filled + line contours in color. Returns True if drawn."""
    if psi is None or r_c is None or z_c is None:
        return False
    psi = np.asarray(psi, dtype=float)
    R = np.asarray(r_c, dtype=float)
    Z = np.asarray(z_c, dtype=float)
    try:
        if R.ndim == 2 and Z.ndim == 2 and psi.shape == R.shape:
            RR, ZZ, field = R, Z, psi
        elif R.ndim == 1 and Z.ndim == 1 and psi.shape == (len(Z), len(R)):
            RR, ZZ = np.meshgrid(R, Z)
            field = psi
        elif R.ndim == 1 and Z.ndim == 1 and psi.shape == (len(R), len(Z)):
            RR, ZZ = np.meshgrid(R, Z)
            field = psi.T
        else:
            return False
        finite = np.isfinite(field)
        if not finite.any():
            return False
        levels = np.linspace(
            float(np.nanmin(field[finite])),
            float(np.nanmax(field[finite])),
            int(max(8, n_levels)),
        )
        ax.contourf(RR, ZZ, field, levels=levels, cmap=cmap, alpha=0.92)
        ax.contour(RR, ZZ, field, levels=levels[::2], colors="0.25", linewidths=0.35, alpha=0.55)
        return True
    except Exception:
        return False


def write_freegsnke_efit_side_by_side_gif(
    *,
    run_dir: Path,
    shot: int,
    ds: Any,
    times: np.ndarray,
    lcfs_r_name: str,
    lcfs_z_name: str,
    psi_var: str,
    out_dir: Path,
    n_frames: int = 16,
    fps: float = 2.0,
) -> Dict[str, Any]:
    """Write dual-panel GIF: FreeGSNKE (left, color) | EFIT++ archive (right, color).

    Matches the FreeGSNKE README demo layout for classic MAST using archive EFIT++.
    Soft-skips when matplotlib/Pillow/LCFS missing (never invents contours).
    """
    from .efit_compare import _extract_lcfs_at, _extract_psi_at, _nearest_index, _rel
    from .equilibrium_presentation import write_gif_from_pngs
    from .freegsnke_lcfs import load_inverse_dump, plasma_psi_pack_from_dump

    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    frames_dir = out_dir / "side_by_side_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    report: Dict[str, Any] = {
        "ok": False,
        "n_frames_requested": int(n_frames),
        "n_frames_written": 0,
        "gif_rel": None,
        "frame_rels": [],
        "freegsnke_source": None,
        "notes": [],
        "errors": [],
    }
    if not _HAS_MPL:
        report["errors"].append("matplotlib_unavailable")
        return report
    n_frames = max(2, min(int(n_frames), 48))
    t0, t1 = _load_window(run_dir)
    if t0 is None or t1 is None or not (float(t1) > float(t0)):
        finite = times[np.isfinite(times)]
        if len(finite) < 2:
            report["errors"].append("insufficient_efit_times")
            return report
        t0, t1 = float(finite[0]), float(finite[-1])
        report["notes"].append("window_missing_used_efit_time_span")
    query_times = np.linspace(float(t0), float(t1), n_frames)
    fg_series = _freegsnke_lcfs_timeseries(run_dir)
    fg_psi_pack = plasma_psi_pack_from_dump(load_inverse_dump(run_dir) or {})
    if not fg_series:
        report["notes"].append("freegsnke_lcfs_unavailable_efit_only_right_panel")
    else:
        report["freegsnke_source"] = fg_series[0].get("source")
        if fg_series[0].get("t") is None and len(fg_series) == 1:
            report["notes"].append(
                "freegsnke_single_time_lcfs_repeated_across_frames_honest_label"
            )
        elif fg_series[0].get("t") is not None and len(fg_series) == 1:
            report["notes"].append(
                "freegsnke_single_time_lcfs_repeated_across_frames_honest_label"
            )

    frame_paths: List[Path] = []
    for k, tq in enumerate(query_times):
        idx = _nearest_index(times, float(tq))
        t_efit = float(times[idx]) if idx < len(times) else float(tq)
        lcfs = _extract_lcfs_at(ds, idx, lcfs_r_name, lcfs_z_name)
        psi_pack = _extract_psi_at(ds, idx, psi_var)
        fg = _nearest_fg(fg_series, t_efit)
        pf = _load_pf_currents_panel(run_dir, t_efit)

        fig, axes = plt.subplots(1, 2, figsize=(11.0, 6.4), sharex=False, sharey=False)
        ax_l, ax_r = axes

        # Left — FreeGSNKE (color ψ + LCFS)
        ax_l.set_title("FreeGSNKE (classic MAST)", fontsize=11, color="#0b3d5c")
        drawn_l = False
        if fg_psi_pack is not None:
            drawn_l = _draw_colored_psi(
                ax_l,
                fg_psi_pack["psi"],
                fg_psi_pack["R"],
                fg_psi_pack["Z"],
                cmap="magma",
                n_levels=22,
            )
        if fg is not None:
            ax_l.plot(
                fg["R"],
                fg["Z"],
                color="#00e5ff",
                lw=2.2,
                label="FreeGSNKE LCFS",
                zorder=5,
            )
            if fg.get("t") is not None:
                ax_l.text(
                    0.02,
                    0.98,
                    f"t≈{float(fg['t']):.4f}s",
                    transform=ax_l.transAxes,
                    va="top",
                    fontsize=8,
                    color="0.15",
                    bbox=dict(boxstyle="round,pad=0.2", fc="w", ec="none", alpha=0.7),
                )
            else:
                ax_l.text(
                    0.02,
                    0.98,
                    "single-time LCFS (repeated)",
                    transform=ax_l.transAxes,
                    va="top",
                    fontsize=8,
                    color="0.25",
                    bbox=dict(boxstyle="round,pad=0.2", fc="w", ec="none", alpha=0.7),
                )
        elif not drawn_l:
            ax_l.text(
                0.5,
                0.5,
                "FreeGSNKE LCFS\nunavailable",
                ha="center",
                va="center",
                transform=ax_l.transAxes,
                color="0.5",
            )
        ax_l.set_aspect("equal", adjustable="datalim")
        ax_l.set_xlabel("R (m)")
        ax_l.set_ylabel("Z (m)")
        ax_l.grid(True, alpha=0.25)
        if fg is not None or drawn_l:
            ax_l.legend(loc="best", fontsize=7, frameon=False)

        # Right — EFIT++ archive (color ψ + LCFS)
        ax_r.set_title("EFIT++ archive (FAIR-MAST)", fontsize=11, color="#5c2d0b")
        drawn_r = False
        if psi_pack is not None:
            drawn_r = _draw_colored_psi(
                ax_r,
                psi_pack["psi"],
                psi_pack.get("r"),
                psi_pack.get("z"),
                cmap="viridis",
                n_levels=22,
            )
            if not drawn_r:
                report.setdefault("psi_contour_skips", 0)
                report["psi_contour_skips"] = int(report["psi_contour_skips"]) + 1
        if lcfs is not None:
            ax_r.plot(
                lcfs[0],
                lcfs[1],
                color="#ffb703",
                lw=2.2,
                label="EFIT++ LCFS",
                zorder=5,
            )
        elif not drawn_r:
            ax_r.text(
                0.5,
                0.5,
                "EFIT LCFS\nunavailable",
                ha="center",
                va="center",
                transform=ax_r.transAxes,
                color="0.5",
            )
        if fg is not None:
            ax_r.plot(
                fg["R"],
                fg["Z"],
                color="#00e5ff",
                ls="--",
                lw=1.5,
                alpha=0.95,
                label="FreeGSNKE (overlay)",
                zorder=6,
            )
        ax_r.set_aspect("equal", adjustable="datalim")
        ax_r.set_xlabel("R (m)")
        ax_r.set_ylabel("Z (m)")
        ax_r.grid(True, alpha=0.25)
        ax_r.legend(loc="best", fontsize=7, frameon=False)

        # Shared axis limits when both have geometry
        xs: List[float] = []
        ys: List[float] = []
        for ax in (ax_l, ax_r):
            for line in ax.get_lines():
                xd = line.get_xdata()
                yd = line.get_ydata()
                if len(xd) and len(yd):
                    xs.extend([float(np.nanmin(xd)), float(np.nanmax(xd))])
                    ys.extend([float(np.nanmin(yd)), float(np.nanmax(yd))])
        if xs and ys:
            pad_x = 0.05 * (max(xs) - min(xs) + 1e-3)
            pad_y = 0.05 * (max(ys) - min(ys) + 1e-3)
            for ax in (ax_l, ax_r):
                ax.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
                ax.set_ylim(min(ys) - pad_y, max(ys) + pad_y)

        footer = (
            f"Shot {shot}  ·  t = {t_efit:.4f} s  ·  "
            "FreeGSNKE vs FAIR-MAST EFIT++ (classic MAST, colored ψ)"
        )
        if pf:
            bits = [f"{k}={v/1e3:.1f}kA" for k, v in list(pf.items())[:6]]
            footer += "  ·  I: " + ", ".join(bits)
        fig.suptitle(footer, fontsize=9)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        fp = frames_dir / f"sbs_{k:03d}.png"
        fig.savefig(fp, dpi=120, bbox_inches="tight")
        plt.close(fig)
        frame_paths.append(fp)
        report["frame_rels"].append(_rel(run_dir, fp))

    report["n_frames_written"] = len(frame_paths)
    gif_path = out_dir / "freegsnke_efit_side_by_side.gif"
    gif_rep = write_gif_from_pngs(frame_paths, gif_path, fps=float(fps))
    if gif_rep.get("ok"):
        report["ok"] = True
        report["gif_rel"] = _rel(run_dir, gif_path)
        report["fps"] = float(fps)
    else:
        report["errors"].extend(list(gif_rep.get("errors") or []))
        report["ok"] = len(frame_paths) >= 2
        report["notes"].append("gif_stitch_failed_frames_kept")
    meta_path = out_dir / "side_by_side_meta.json"
    meta_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["meta_rel"] = _rel(run_dir, meta_path)
    return report
