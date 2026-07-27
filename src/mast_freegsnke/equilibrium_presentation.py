"""Equilibrium frame + GIF presentation helpers (formed-plasma window).

Presentation only: stitch declared solve frames into animated GIFs.
Never invents equilibria — callers must supply PNG frames from real solves.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


class PresentationError(ValueError):
    pass


@dataclass(frozen=True)
class PresentationAuthority:
    """Declared presentation knobs (snapshotted under inputs/)."""

    version: str = "1.0"
    write_equilibrium_gifs: bool = True
    write_eq_frames: bool = True
    gif_fps: float = 2.0
    gif_dpi: int = 100
    notes: str = (
        "PNG frames + GIFs across the finalized formed-plasma window "
        "(linspace_window_inclusive for inverse/forward; evolutive steps for nlstepper). "
        "Not a substitute for metrics CSVs; skipped/failed solves omit frames."
    )

    def validate(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise PresentationError("version required")
        if not isinstance(self.write_equilibrium_gifs, bool):
            raise PresentationError("write_equilibrium_gifs must be bool")
        if not isinstance(self.write_eq_frames, bool):
            raise PresentationError("write_eq_frames must be bool")
        if not (isinstance(self.gif_fps, (int, float)) and float(self.gif_fps) > 0.0):
            raise PresentationError("gif_fps must be > 0")
        if not (isinstance(self.gif_dpi, int) and 50 <= int(self.gif_dpi) <= 400):
            raise PresentationError("gif_dpi must be int in [50, 400]")
        if self.write_equilibrium_gifs and not self.write_eq_frames:
            raise PresentationError(
                "write_equilibrium_gifs=true requires write_eq_frames=true "
                "(GIF needs PNG frames from real solves)"
            )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_presentation_authority(path: Path) -> PresentationAuthority:
    if not path.exists():
        raise PresentationError(f"missing presentation authority: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise PresentationError("presentation authority root must be an object")
    auth = PresentationAuthority(
        version=str(obj.get("version", "1.0")),
        write_equilibrium_gifs=bool(obj.get("write_equilibrium_gifs", True)),
        write_eq_frames=bool(obj.get("write_eq_frames", True)),
        gif_fps=float(obj.get("gif_fps", 2.0)),
        gif_dpi=int(obj.get("gif_dpi", 100)),
        notes=str(obj.get("notes", PresentationAuthority.notes)),
    )
    auth.validate()
    return auth


def try_load_presentation_authority(inputs_dir: Path) -> Optional[PresentationAuthority]:
    path = Path(inputs_dir) / "presentation_authority.json"
    if not path.exists():
        return None
    return load_presentation_authority(path)


def write_presentation_authority(inputs_dir: Path, auth: PresentationAuthority) -> Path:
    auth.validate()
    out = Path(inputs_dir) / "presentation_authority.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(auth.to_dict(), indent=2) + "\n", encoding="utf-8")
    return out


def overlay_honest_xpoints(ax: Any, eq: Any) -> None:
    """Mark primary X (on drawn separatrix) vs secondary nulls (ψ≠ψ_bndry).

    freegs4e draws *all* critical X as red × while the separatrix contour uses
    only ``xpt[0]`` ψ. Secondary × therefore sit off the red LCFS and look like
    a bug. Presentation must not imply every × lies on the LCFS.
    """
    try:
        xpt = eq._profiles.xpt
    except Exception:
        return
    if xpt is None:
        return
    try:
        n = len(xpt)
    except TypeError:
        return
    if n < 1:
        return

    # Primary: thick red × — this is the null whose ψ defines the separatrix.
    try:
        r0, z0 = float(xpt[0][0]), float(xpt[0][1])
        ax.plot(
            r0,
            z0,
            "rx",
            markersize=11,
            markeredgewidth=2.8,
            zorder=6,
            label="primary X (ψ=ψ_bndry)",
        )
    except Exception:
        pass
    # Secondary: faint gray × — critical points at different ψ, not on LCFS.
    for i in range(1, n):
        try:
            ri, zi = float(xpt[i][0]), float(xpt[i][1])
            ax.plot(
                ri,
                zi,
                "x",
                color="0.55",
                markersize=8,
                markeredgewidth=1.4,
                zorder=5,
                label="secondary null (≠LCFS)" if i == 1 else None,
            )
        except Exception:
            continue


def load_inverse_null_targets(run_dir: Path) -> Optional[Dict[str, Any]]:
    """Load Inverse X/O targets from execution_authority boundary (archive-remapped)."""
    run_dir = Path(run_dir)
    for rel in (
        "inputs/execution_authority/boundary_from_shape_targets.json",
        "inputs/execution_authority/boundary_spec.json",
        "inputs/execution_authority/execution_authority_bundle.json",
    ):
        p = run_dir / rel
        if not p.is_file():
            continue
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        # Prefer provenance with explicit null_points dict
        np_prov = obj.get("null_points")
        if isinstance(np_prov, dict) and np_prov.get("o_point"):
            out: Dict[str, Any] = {
                "source": rel,
                "null_topology": obj.get("null_topology"),
                "o_point": np_prov.get("o_point"),
            }
            if np_prov.get("x_point"):
                out["x_points"] = [np_prov["x_point"]]
            else:
                xs = []
                for key in ("x_point_lower", "x_point_upper", "x_point_primary_archive"):
                    if np_prov.get(key):
                        xs.append(np_prov[key])
                if xs:
                    out["x_points"] = xs
            tips = obj.get("divertor_tips")
            if isinstance(tips, list) and tips:
                out["divertor_tips"] = tips
            return out
        # Raw BoundarySpec: null_points = [[R...],[Z...]]
        raw = obj.get("null_points") or (obj.get("boundary") or {}).get("null_points")
        if isinstance(raw, list) and len(raw) >= 2:
            try:
                rr = [float(v) for v in raw[0]]
                zz = [float(v) for v in raw[1]]
            except (TypeError, ValueError):
                continue
            if len(rr) >= 2 and len(rr) == len(zz):
                # Convention: first = primary X, second = O, optional further X
                xs = [[rr[0], zz[0]]]
                for i in range(2, len(rr)):
                    xs.append([rr[i], zz[i]])
                return {
                    "source": rel,
                    "x_points": xs,
                    "o_point": [rr[1], zz[1]],
                    "null_topology": "double_null" if len(xs) >= 2 else "single_null",
                }
    return None


def overlay_inverse_targets(
    ax: Any,
    targets: Optional[Dict[str, Any]],
) -> None:
    """Overlay Inverse constraint targets (archive X/O) — distinct from solved ×."""
    if not targets:
        return
    labeled_x = False
    for xp in targets.get("x_points") or []:
        try:
            ax.plot(
                float(xp[0]),
                float(xp[1]),
                "r+",
                ms=14,
                mew=2.0,
                zorder=7,
                label="X target (Inverse)" if not labeled_x else None,
            )
            labeled_x = True
        except Exception:
            continue
    op = targets.get("o_point")
    if op is not None:
        try:
            ax.plot(
                float(op[0]),
                float(op[1]),
                "bo",
                ms=6,
                zorder=7,
                label="O target (Inverse)",
            )
        except Exception:
            pass


def plot_equilibrium_curated(
    ax: Any,
    eq: Any,
    tokamak: Any = None,
    *,
    n_core_contours: int = 10,
    show_open_field: bool = False,
    n_open_contours: int = 4,
    inverse_targets: Optional[Dict[str, Any]] = None,
) -> None:
    """Curated ψ plot: wall + nested core surfaces + LCFS + honest X/O.

    Avoids freegs4e default (35 global levels + all-red ×) which looks noisy
    near coils and implies secondary nulls lie on the separatrix.
    Optional ``inverse_targets`` overlays archive Inverse X/O (+/o).
    """
    import numpy as np
    from numpy import amax, amin, linspace

    try:
        psi = np.asarray(eq.psi(), dtype=float)
        opt = eq._profiles.opt
        xpt = eq._profiles.xpt
    except Exception as e:
        raise PresentationError(f"equilibrium not solved for curated plot: {e}") from e

    if tokamak is not None:
        try:
            tokamak.plot(axis=ax, show=False)
        except Exception:
            pass

    # Prefer ψ_bndry from primary X; fall back to profiles attribute.
    try:
        psi_bndry = float(xpt[0][2])
    except Exception:
        psi_bndry = float(getattr(eq, "psi_bndry", float("nan")))
    try:
        psi_axis = float(opt[0][2])
    except Exception:
        psi_axis = float(getattr(eq, "psi_axis", float("nan")))

    R = eq.R
    Z = eq.Z
    # Core nested surfaces strictly between axis and boundary (exclusive).
    if np.isfinite(psi_axis) and np.isfinite(psi_bndry) and abs(psi_bndry - psi_axis) > 0.0:
        lo, hi = (psi_axis, psi_bndry) if psi_axis < psi_bndry else (psi_bndry, psi_axis)
        # Exclude exact axis/boundary endpoints for cleaner nesting.
        core_levels = linspace(lo, hi, int(n_core_contours) + 2)[1:-1]
        if len(core_levels) > 0:
            ax.contour(
                R,
                Z,
                psi,
                levels=core_levels,
                colors="0.35",
                linewidths=0.7,
                alpha=0.85,
            )
    elif show_open_field:
        levels = linspace(amin(psi), amax(psi), 12)
        ax.contour(R, Z, psi, levels=levels, linewidths=0.5, alpha=0.5)

    # Optional muted open-field contours outside LCFS (never denser than core).
    if show_open_field and np.isfinite(psi_bndry):
        outside = psi[np.isfinite(psi)]
        if psi_axis < psi_bndry:
            cand = outside[outside > psi_bndry]
        else:
            cand = outside[outside < psi_bndry]
        if cand.size > 8:
            open_levels = linspace(float(amin(cand)), float(amax(cand)), int(n_open_contours) + 2)[1:-1]
            ax.contour(
                R,
                Z,
                psi,
                levels=open_levels,
                colors="0.65",
                linewidths=0.4,
                alpha=0.35,
                linestyles=":",
            )

    # Separatrix / LCFS at primary-X ψ
    if np.isfinite(psi_bndry):
        ax.contour(
            R,
            Z,
            psi,
            levels=[psi_bndry],
            colors="r",
            linewidths=2.0,
            linestyles="solid",
        )
        ax.plot([], [], "r-", lw=2.0, label="LCFS (primary X ψ)")

    # O-points (magnetic axis first)
    try:
        for i, row in enumerate(opt):
            ax.plot(
                float(row[0]),
                float(row[1]),
                "g2",
                markersize=10 if i == 0 else 7,
                markeredgewidth=1.8 if i == 0 else 1.0,
                zorder=6,
                label="O-point (axis)" if i == 0 else None,
            )
    except Exception:
        pass

    overlay_honest_xpoints(ax, eq)
    overlay_inverse_targets(ax, inverse_targets)
    ax.set_aspect("equal")
    ax.grid(alpha=0.25)
    ax.set_xlabel("Major radius [m]")
    ax.set_ylabel("Height [m]")


def save_equilibrium_png(
    *,
    tokamak: Any,
    eq: Any,
    out_path: Path,
    title: str,
    dpi: int = 100,
    figsize: tuple[float, float] = (4.0, 8.0),
    curated: bool = True,
    inverse_targets: Optional[Dict[str, Any]] = None,
    run_dir: Optional[Path] = None,
) -> Path:
    """Save one equilibrium PNG frame (Agg-safe).

    Default ``curated=True``: core surfaces + LCFS + honest X/O (not freegs4e's
    dense global contour soup). Separatrix is primary-X ψ only.
    When ``run_dir`` is set, archive Inverse X/O targets are overlaid if present.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if inverse_targets is None and run_dir is not None:
        inverse_targets = load_inverse_null_targets(Path(run_dir))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)
    if curated:
        try:
            plot_equilibrium_curated(ax, eq, tokamak, inverse_targets=inverse_targets)
        except Exception as e:
            plt.close(fig)
            raise PresentationError(f"curated plot failed: {e}") from e
    else:
        try:
            tokamak.plot(axis=ax, show=False)
        except Exception:
            pass
        try:
            eq.plot(axis=ax, show=False, xpoints=False, opoints=True)
        except TypeError:
            try:
                eq.plot(axis=ax, show=False)
            except Exception as e:
                plt.close(fig)
                raise PresentationError(f"eq.plot failed: {e}") from e
        except Exception as e:
            plt.close(fig)
            raise PresentationError(f"eq.plot failed: {e}") from e
        overlay_honest_xpoints(ax, eq)
        overlay_inverse_targets(ax, inverse_targets)
        ax.set_aspect("equal")
        ax.grid(alpha=0.3)
    ax.set_title(title)
    try:
        ax.legend(loc="upper right", fontsize=7, framealpha=0.85)
    except Exception:
        pass
    fig.tight_layout()
    fig.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out_path


def write_gif_from_pngs(
    frame_paths: Sequence[Path],
    out_gif: Path,
    *,
    fps: float = 2.0,
    loop: int = 0,
) -> Dict[str, Any]:
    """Stitch ordered PNG frames into an animated GIF via Pillow.

    Fail-closed if Pillow missing or fewer than 2 frames (single frame is not a GIF).
    """
    frames = [Path(p) for p in frame_paths if Path(p).exists()]
    report: Dict[str, Any] = {
        "ok": False,
        "out_gif": str(out_gif),
        "n_frames": len(frames),
        "fps": float(fps),
        "errors": [],
    }
    if len(frames) < 2:
        report["errors"].append(
            f"need_at_least_2_frames_for_gif:got={len(frames)}"
        )
        return report
    if not (isinstance(fps, (int, float)) and float(fps) > 0.0):
        report["errors"].append(f"invalid_fps:{fps!r}")
        return report
    try:
        from PIL import Image
    except ImportError as e:
        report["errors"].append(
            f"pillow_required_for_gif: {e}. Install pillow (dependency of mast-freegsnke-pipeline)."
        )
        return report

    images: List[Any] = []
    try:
        for p in frames:
            images.append(Image.open(p).convert("P", palette=Image.ADAPTIVE))
        duration_ms = max(1, int(round(1000.0 / float(fps))))
        out_gif = Path(out_gif)
        out_gif.parent.mkdir(parents=True, exist_ok=True)
        images[0].save(
            out_gif,
            save_all=True,
            append_images=images[1:],
            duration=duration_ms,
            loop=int(loop),
            optimize=False,
        )
    finally:
        for im in images:
            try:
                im.close()
            except Exception:
                pass

    report["ok"] = True
    report["duration_ms_per_frame"] = max(1, int(round(1000.0 / float(fps))))
    report["frame_paths"] = [str(p) for p in frames]
    return report


def sorted_frame_paths(directory: Path, glob_pat: str = "*.png") -> List[Path]:
    d = Path(directory)
    if not d.is_dir():
        return []
    return sorted(d.glob(glob_pat))


def presentation_gifs_under(run_dir: Path) -> Dict[str, str]:
    """Discover written GIFs for expert summary (relative paths)."""
    root = Path(run_dir)
    from .shot_layout import resolve_run_path

    candidates = {
        "inverse": resolve_run_path(
            root,
            "03_reconstruction/presentation/inverse_equilibria.gif",
            "presentation/inverse_equilibria.gif",
        ),
        "forward": resolve_run_path(
            root,
            "03_reconstruction/presentation/forward_equilibria.gif",
            "presentation/forward_equilibria.gif",
        ),
        "evolutive": resolve_run_path(
            root,
            "03_reconstruction/evolutive/evolutive_equilibria.gif",
            "evolutive/evolutive_equilibria.gif",
        ),
    }
    out: Dict[str, str] = {}
    for k, p in candidates.items():
        if p is not None and p.exists():
            out[k] = str(p.relative_to(root)).replace("\\", "/")
    return out
