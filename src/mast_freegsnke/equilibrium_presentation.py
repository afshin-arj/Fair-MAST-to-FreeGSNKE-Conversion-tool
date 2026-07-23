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


def save_equilibrium_png(
    *,
    tokamak: Any,
    eq: Any,
    out_path: Path,
    title: str,
    dpi: int = 100,
    figsize: tuple[float, float] = (4.0, 8.0),
) -> Path:
    """Save one equilibrium PNG frame (Agg-safe)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)
    try:
        tokamak.plot(axis=ax, show=False)
    except Exception:
        pass
    try:
        eq.plot(axis=ax, show=False)
    except Exception as e:
        plt.close(fig)
        raise PresentationError(f"eq.plot failed: {e}") from e
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    ax.set_title(title)
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
