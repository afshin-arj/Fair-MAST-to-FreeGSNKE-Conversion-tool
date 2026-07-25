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
    from .efit_compare import _try_freegsnke_products

    out: List[Dict[str, Any]] = []
    for rel in (
        "03_reconstruction/freegsnke_lcfs_timeseries.csv",
        "03_reconstruction/presentation/freegsnke_lcfs_timeseries.csv",
        "presentation/freegsnke_lcfs_timeseries.csv",
    ):
        p = Path(run_dir) / rel
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
                out.append({"t": float(t), "R": rr[m], "Z": zz[m], "source": rel})
        if out:
            return out

    fg, _ = _try_freegsnke_products(Path(run_dir))
    if fg is not None:
        out.append(
            {
                "t": None,
                "R": fg[0],
                "Z": fg[1],
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
    """Write dual-panel GIF: FreeGSNKE LCFS (left) | EFIT++ archive (right).

    Matches the FreeGSNKE README demo layout for classic MAST using archive EFIT++.
    Soft-skips when matplotlib/Pillow/LCFS missing (never invents contours).
    """
    from .efit_compare import _extract_lcfs_at, _extract_psi_at, _nearest_index, _rel
    from .equilibrium_presentation import write_gif_from_pngs

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
        # Fall back to full EFIT time span
        finite = times[np.isfinite(times)]
        if len(finite) < 2:
            report["errors"].append("insufficient_efit_times")
            return report
        t0, t1 = float(finite[0]), float(finite[-1])
        report["notes"].append("window_missing_used_efit_time_span")
    query_times = np.linspace(float(t0), float(t1), n_frames)
    fg_series = _freegsnke_lcfs_timeseries(run_dir)
    if not fg_series:
        report["notes"].append("freegsnke_lcfs_unavailable_efit_only_right_panel")
    else:
        report["freegsnke_source"] = fg_series[0].get("source")
        if fg_series[0].get("t") is None and len(fg_series) == 1:
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

        fig, axes = plt.subplots(1, 2, figsize=(10.5, 6.2), sharex=False, sharey=False)
        ax_l, ax_r = axes

        # Left — FreeGSNKE
        ax_l.set_title("FreeGSNKE (classic MAST)", fontsize=11)
        if fg is not None:
            ax_l.plot(fg["R"], fg["Z"], "C3-", lw=1.8, label="FreeGSNKE LCFS")
            if fg.get("t") is not None:
                ax_l.text(
                    0.02,
                    0.98,
                    f"t≈{float(fg['t']):.4f}s",
                    transform=ax_l.transAxes,
                    va="top",
                    fontsize=8,
                    color="0.35",
                )
            else:
                ax_l.text(
                    0.02,
                    0.98,
                    "single-time LCFS (repeated)",
                    transform=ax_l.transAxes,
                    va="top",
                    fontsize=8,
                    color="0.45",
                )
        else:
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
        ax_l.grid(True, alpha=0.3)
        ax_l.legend(loc="best", fontsize=7, frameon=False)

        # Right — EFIT++ archive
        ax_r.set_title("EFIT++ archive (FAIR-MAST)", fontsize=11)
        if psi_pack is not None:
            psi = psi_pack["psi"]
            r_c, z_c = psi_pack.get("r"), psi_pack.get("z")
            drawn = False
            if r_c is not None and z_c is not None and len(r_c) > 1 and len(z_c) > 1:
                try:
                    if psi.shape == (len(z_c), len(r_c)):
                        RR, ZZ = np.meshgrid(r_c, z_c)
                        ax_r.contour(RR, ZZ, psi, levels=18, colors="0.55", linewidths=0.6)
                        drawn = True
                    elif psi.shape == (len(r_c), len(z_c)):
                        RR, ZZ = np.meshgrid(r_c, z_c)
                        ax_r.contour(RR, ZZ, psi.T, levels=18, colors="0.55", linewidths=0.6)
                        drawn = True
                except Exception:
                    drawn = False
            if not drawn:
                report.setdefault("psi_contour_skips", 0)
                report["psi_contour_skips"] = int(report["psi_contour_skips"]) + 1
        if lcfs is not None:
            ax_r.plot(lcfs[0], lcfs[1], "k-", lw=1.8, label="EFIT++ LCFS")
        else:
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
            ax_r.plot(fg["R"], fg["Z"], "C3--", lw=1.2, alpha=0.85, label="FreeGSNKE (overlay)")
        ax_r.set_aspect("equal", adjustable="datalim")
        ax_r.set_xlabel("R (m)")
        ax_r.set_ylabel("Z (m)")
        ax_r.grid(True, alpha=0.3)
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

        footer = f"Shot {shot}  ·  t = {t_efit:.4f} s  ·  FreeGSNKE vs FAIR-MAST EFIT++ (classic MAST)"
        if pf:
            # Show a few coil currents
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
        # Still useful as frame sequence
        report["ok"] = len(frame_paths) >= 2
        report["notes"].append("gif_stitch_failed_frames_kept")
    meta_path = out_dir / "side_by_side_meta.json"
    meta_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    report["meta_rel"] = _rel(run_dir, meta_path)
    return report
