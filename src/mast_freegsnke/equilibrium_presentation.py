"""Equilibrium frame + GIF presentation helpers (formed-plasma window).

Presentation only: stitch declared solve frames into animated GIFs.
Never invents equilibria — callers must supply PNG frames from real solves.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


class PresentationError(ValueError):
    pass


def apply_equal_aspect_rz(
    ax: Any,
    *,
    xlim: Optional[Tuple[float, float]] = None,
    ylim: Optional[Tuple[float, float]] = None,
) -> None:
    """Equal R–Z aspect without Matplotlib 'Ignoring fixed x limits' spam.

    Set data limits first (optional), then ``adjustable='box'`` so the axes
    box absorbs aspect — never ``datalim`` after fixed ``set_xlim``.
    """
    try:
        if xlim is not None:
            ax.set_xlim(float(xlim[0]), float(xlim[1]))
        if ylim is not None:
            ax.set_ylim(float(ylim[0]), float(ylim[1]))
        ax.set_aspect("equal", adjustable="box")
    except Exception:
        try:
            ax.set_aspect("equal")
        except Exception:
            pass


def _iter_machine_coil_filaments(tokamak: Any) -> List[Tuple[float, float, float, float]]:
    """Yield (R, Z, half_width_R, half_height_Z) for active (+passive) filaments."""
    import numpy as np

    out: List[Tuple[float, float, float, float]] = []
    coil_lists: List[Any] = []
    coils = getattr(tokamak, "coils", None)
    if coils is not None:
        coil_lists.append(coils)
    for attr in ("passive_coils", "passives"):
        pas = getattr(tokamak, attr, None)
        if pas is not None:
            coil_lists.append(pas)

    for clist in coil_lists:
        try:
            entries = list(clist)
        except Exception:
            continue
        for entry in entries:
            try:
                coil = entry[1] if isinstance(entry, (list, tuple)) and len(entry) >= 2 else entry
            except Exception:
                continue
            nested = getattr(coil, "coils", None) or [coil]
            try:
                nested_iter = list(nested)
            except Exception:
                nested_iter = [coil]
            for item in nested_iter:
                try:
                    mc = item[1] if isinstance(item, (list, tuple)) and len(item) >= 2 else item
                except Exception:
                    mc = item
                try:
                    rf = np.asarray(getattr(mc, "Rfil", getattr(mc, "R", [])), dtype=float).ravel()
                    zf = np.asarray(getattr(mc, "Zfil", getattr(mc, "Z", [])), dtype=float).ravel()
                except Exception:
                    continue
                if rf.size == 0 or zf.size == 0:
                    continue
                try:
                    dR = float(np.asarray(getattr(mc, "dR", 0.02), dtype=float).ravel()[0])
                except Exception:
                    dR = 0.02
                try:
                    dZ = float(np.asarray(getattr(mc, "dZ", 0.02), dtype=float).ravel()[0])
                except Exception:
                    dZ = 0.02
                dR = max(abs(dR), 1.0e-3)
                dZ = max(abs(dZ), 1.0e-3)
                n = int(min(rf.size, zf.size))
                for i in range(n):
                    if np.isfinite(rf[i]) and np.isfinite(zf[i]):
                        out.append((float(rf[i]), float(zf[i]), dR, dZ))
    return out


def structure_safe_contour_mask(
    tokamak: Any,
    R: Any,
    Z: Any,
    *,
    coil_pad: float = 1.35,
) -> Any:
    """Boolean mask: True where ψ contours may be drawn.

    Keeps points **inside** the limiter/wall polygon and **outside** active
    (and passive, if present) coil filament rectangles — so vacuum/open-field
    contours do not visually cut through the solenoid, PF coils, or limiter.
    Presentation only; never invents metrology.
    """
    import numpy as np

    Rm = np.asarray(R, dtype=float)
    Zm = np.asarray(Z, dtype=float)
    if Rm.shape != Zm.shape:
        return np.ones(Rm.shape, dtype=bool)

    allow = np.ones(Rm.shape, dtype=bool)

    lim = getattr(tokamak, "limiter", None)
    if lim is not None:
        try:
            lr = np.asarray(getattr(lim, "R"), dtype=float).ravel()
            lz = np.asarray(getattr(lim, "Z"), dtype=float).ravel()
            m = np.isfinite(lr) & np.isfinite(lz)
            lr, lz = lr[m], lz[m]
            if lr.size >= 3:
                from matplotlib.path import Path as MplPath

                poly = MplPath(np.column_stack([lr, lz]))
                pts = np.column_stack([Rm.ravel(), Zm.ravel()])
                allow &= poly.contains_points(pts).reshape(Rm.shape)
        except Exception:
            pass

    pad = float(coil_pad) if coil_pad and coil_pad > 0.0 else 1.0
    for r0, z0, dR, dZ in _iter_machine_coil_filaments(tokamak):
        hw = pad * float(dR)
        hh = pad * float(dZ)
        allow &= ~((np.abs(Rm - r0) <= hw) & (np.abs(Zm - z0) <= hh))

    return allow


def mask_psi_for_structure_safe_contours(
    psi: Any,
    R: Any,
    Z: Any,
    tokamak: Any,
    *,
    coil_pad: float = 1.35,
) -> Any:
    """Copy of ψ with NaN outside limiter and inside coil rectangles."""
    import numpy as np

    arr = np.array(np.asarray(psi, dtype=float), copy=True)
    if tokamak is None:
        return arr
    try:
        allow = structure_safe_contour_mask(tokamak, R, Z, coil_pad=coil_pad)
        arr[~allow] = np.nan
    except Exception:
        pass
    return arr


@dataclass(frozen=True)
class PresentationAuthority:
    """Declared presentation knobs (snapshotted under inputs/)."""

    version: str = "1.1"
    write_equilibrium_gifs: bool = True
    write_eq_frames: bool = True
    gif_fps: float = 2.0
    gif_dpi: int = 100
    # freegsnke_native = tokamak.plot + eq.plot (+ constrain.plot) like example01a/02/05
    # curated = sparse core surfaces + honest secondary-X legend + dump-LCFS fallback
    # Default curated: Inverse DN honesty — native domain-wide levels pierce coils and
    # hide missing LCFS when xpt empty after restore.
    plot_style: str = "curated"
    # Vacuum/open-field contours outside LCFS (structure-masked — never through coils).
    show_open_field: bool = True
    n_open_contours: int = 6
    notes: str = (
        "PNG frames + GIFs across the finalized formed-plasma window "
        "(linspace_window_inclusive for inverse/forward; evolutive steps for nlstepper). "
        "Default plot_style=curated with structure-masked open-field contours "
        "(inside limiter, not through solenoid/PF coils). freegsnke_native remains "
        "available for example01a-style tokamak.plot+eq.plot. Not a substitute for "
        "metrics CSVs; skipped/failed solves omit frames."
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
        if str(self.plot_style) not in {"freegsnke_native", "curated"}:
            raise PresentationError(
                "plot_style must be 'freegsnke_native' or 'curated'"
            )
        if not isinstance(self.show_open_field, bool):
            raise PresentationError("show_open_field must be bool")
        if not (isinstance(self.n_open_contours, int) and 1 <= int(self.n_open_contours) <= 30):
            raise PresentationError("n_open_contours must be int in [1, 30]")
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
        version=str(obj.get("version", "1.2")),
        write_equilibrium_gifs=bool(obj.get("write_equilibrium_gifs", True)),
        write_eq_frames=bool(obj.get("write_eq_frames", True)),
        gif_fps=float(obj.get("gif_fps", 2.0)),
        gif_dpi=int(obj.get("gif_dpi", 100)),
        plot_style=str(obj.get("plot_style", "curated")),
        show_open_field=bool(obj.get("show_open_field", True)),
        n_open_contours=int(obj.get("n_open_contours", 6)),
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


def attach_profiles_after_restore(
    eq: Any,
    profiles: Any,
) -> bool:
    """Re-bind ``eq._profiles`` and refresh O/X after child-process psi restore.

    Multitime / t0 Inverse solve in a spawn child and only copy ``plasma_psi``
    (and optionally currents) back. Critical points must be found on **total**
    ψ (``eq.psi()`` = plasma + coils); ``plasma_psi`` alone yields false 0-X
    (shot 30201). Also ports ``eq.xpt`` / ``eq.opt`` like FreeGSNKE
    ``port_critical``.
    """
    import numpy as np

    try:
        psi = eq.psi() if callable(getattr(eq, "psi", None)) else getattr(eq, "psi", None)
        if psi is None:
            return False
        psi_arr = np.asarray(psi, dtype=float)
        profiles.Jtor(eq.R, eq.Z, psi_arr)
        eq._profiles = profiles
    except Exception:
        try:
            psi_arr = np.asarray(eq.psi(), dtype=float)
        except Exception:
            return False

    def _has_xpt() -> bool:
        try:
            xpt = getattr(profiles, "xpt", None)
            return xpt is not None and len(xpt) > 0
        except Exception:
            return False

    def _has_opt() -> bool:
        try:
            opt = getattr(profiles, "opt", None)
            return opt is not None and len(opt) > 0
        except Exception:
            return False

    # Always refresh critical on total ψ — Jtor may leave xpt empty or stale.
    try:
        from mast_freegsnke.inverse_shape_honesty import (
            critical_points_from_total_psi,
            port_critical_to_eq,
        )

        ip = float(getattr(profiles, "Ip", 0.0) or 0.0)
        crit = critical_points_from_total_psi(eq, ip=ip)
        if crit.get("ok"):
            port_critical_to_eq(eq, profiles, crit)
    except Exception:
        if not _has_xpt() or not _has_opt():
            try:
                from freegs4e import critical

                ip = float(getattr(profiles, "Ip", 0.0) or 0.0)
                opt2, xpt2 = critical.find_critical(eq.R, eq.Z, psi_arr, None, ip)
                if opt2 is not None and len(opt2) > 0:
                    profiles.opt = opt2
                    try:
                        eq.opt = opt2
                        profiles.psi_axis = float(opt2[0][2])
                    except Exception:
                        pass
                if xpt2 is not None and len(xpt2) > 0:
                    profiles.xpt = xpt2
                    try:
                        eq.xpt = xpt2
                        profiles.psi_bndry = float(xpt2[0][2])
                    except Exception:
                        pass
            except Exception:
                pass

    try:
        eq._profiles = profiles
    except Exception:
        return False
    return _has_opt() or np.isfinite(psi_arr).any()


def overlay_dump_lcfs(
    ax: Any,
    lcfs_r: Any,
    lcfs_z: Any,
    *,
    label: str = "LCFS (dump polyline)",
    r_min: Optional[float] = None,
    r_max: Optional[float] = None,
    z_min: Optional[float] = None,
    z_max: Optional[float] = None,
) -> bool:
    """Draw an LCFS polyline after domain sanitization (never invent points)."""
    from mast_freegsnke.freegsnke_lcfs import sanitize_lcfs_polyline

    cleaned = sanitize_lcfs_polyline(
        lcfs_r,
        lcfs_z,
        r_min=r_min,
        r_max=r_max,
        z_min=z_min,
        z_max=z_max,
    )
    if cleaned is None:
        return False
    rr, zz = cleaned
    ax.plot(
        rr,
        zz,
        "r-",
        lw=2.0,
        zorder=5,
        label=label,
    )
    return True


def load_dump_lcfs(run_dir: Path) -> Optional[Tuple[Any, Any]]:
    """Load ``lcfs_R`` / ``lcfs_Z`` from ``inverse_dump.pkl`` if present."""
    run_dir = Path(run_dir)
    pkl = run_dir / "inverse_dump.pkl"
    if not pkl.is_file():
        return None
    try:
        import pickle

        with open(pkl, "rb") as f:
            dump = pickle.load(f)
    except Exception:
        return None
    if not isinstance(dump, dict):
        return None
    r, z = dump.get("lcfs_R"), dump.get("lcfs_Z")
    if r is None or z is None:
        return None
    return r, z


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


def plot_equilibrium_freegsnke_native(
    ax: Any,
    eq: Any,
    tokamak: Any = None,
    *,
    constrain: Any = None,
    inverse_targets: Optional[Dict[str, Any]] = None,
    profiles: Any = None,
) -> None:
    """Official FreeGSNKE example01a/02/05 plot style.

    ``tokamak.plot`` + ``eq.plot`` (freegs4e: ~35 ψ levels, primary-X red LCFS,
    all X/O markers). Inverse optionally adds ``constrain.plot``. Archive Inverse
    targets are a thin overlay labeled as targets (not solved nulls).
    """
    if profiles is not None:
        attach_profiles_after_restore(eq, profiles)
    elif getattr(eq, "_profiles", None) is None:
        raise PresentationError(
            "eq._profiles missing for freegsnke_native plot "
            "(pass profiles=... or call attach_profiles_after_restore first)"
        )

    if tokamak is not None:
        try:
            tokamak.plot(axis=ax, show=False)
        except Exception:
            pass
    try:
        eq.plot(axis=ax, show=False)
    except TypeError:
        try:
            eq.plot(axis=ax, show=False, xpoints=True, opoints=True)
        except Exception as e:
            raise PresentationError(f"eq.plot failed: {e}") from e
    except Exception as e:
        # freegs4e plotEquilibrium indexes xpt[0]; empty X after a bad restore
        # → fall back to curated contours rather than a blank/crashing frame.
        try:
            plot_equilibrium_curated(ax, eq, tokamak=None, inverse_targets=None)
        except Exception:
            raise PresentationError(f"eq.plot failed: {e}") from e

    if constrain is not None:
        try:
            constrain.plot(axis=ax, show=False)
        except TypeError:
            try:
                constrain.plot(axis=ax)
            except Exception:
                pass
        except Exception:
            pass

    overlay_inverse_targets(ax, inverse_targets)
    try:
        apply_equal_aspect_rz(ax)
    except Exception:
        pass
    try:
        ax.grid(alpha=0.25)
    except Exception:
        pass
    try:
        ax.set_xlabel("Major radius [m]")
        ax.set_ylabel("Height [m]")
    except Exception:
        pass


def plot_equilibrium_curated(
    ax: Any,
    eq: Any,
    tokamak: Any = None,
    *,
    n_core_contours: int = 10,
    show_open_field: bool = True,
    n_open_contours: int = 6,
    inverse_targets: Optional[Dict[str, Any]] = None,
    dump_lcfs: Optional[Tuple[Any, Any]] = None,
    lcfs_label: str = "LCFS (dump polyline)",
    allow_psi_bndry_lcfs_fallback: bool = True,
) -> None:
    """Curated ψ plot: wall + nested core surfaces + LCFS + honest X/O.

    Avoids freegs4e default (35 global levels + all-red ×) which looks noisy
    near coils and implies secondary nulls lie on the separatrix.
    Optional ``inverse_targets`` overlays archive Inverse X/O (+/o).
    Optional ``dump_lcfs`` (R,Z) draws a caller-supplied polyline (Inverse dump
    or live Forward LCFS) — prefer live Forward LCFS on Forward frames.
    LCFS polylines are sanitized to the GS domain (no R≤0 / R<Rmin beaks).
    Open-field contours (default on) are structure-masked: inside limiter only,
    NaN through solenoid/PF coil filament boxes — Inverse/Forward/Evolutive.
    When ``allow_psi_bndry_lcfs_fallback=False`` (Forward/Evolutive), never
    substitute an unmasked ψ=ψ_bndry contour that snakes through the solenoid.
    """
    import numpy as np
    from numpy import amax, amin, linspace

    from mast_freegsnke.freegsnke_lcfs import grid_bounds_from_eq

    try:
        psi = np.asarray(eq.psi(), dtype=float)
        prof = getattr(eq, "_profiles", None)
        if prof is None:
            raise PresentationError("eq._profiles missing (call attach_profiles_after_restore)")
        opt = getattr(prof, "opt", None)
        xpt = getattr(prof, "xpt", None)
    except PresentationError:
        raise
    except Exception as e:
        raise PresentationError(f"equilibrium not solved for curated plot: {e}") from e

    if tokamak is not None:
        try:
            tokamak.plot(axis=ax, show=False)
        except Exception:
            pass

    # Prefer ψ_bndry from primary X; then profiles attrs; then eq attrs.
    psi_bndry = float("nan")
    psi_axis = float("nan")
    try:
        psi_bndry = float(xpt[0][2])
    except Exception:
        for src in (prof, eq):
            try:
                v = float(getattr(src, "psi_bndry"))
                if np.isfinite(v):
                    psi_bndry = v
                    break
            except Exception:
                pass
    try:
        psi_axis = float(opt[0][2])
    except Exception:
        for src in (prof, eq):
            try:
                v = float(getattr(src, "psi_axis"))
                if np.isfinite(v):
                    psi_axis = v
                    break
            except Exception:
                pass

    R = eq.R
    Z = eq.Z
    # Structure-safe ψ: NaN outside limiter and inside coil/solenoid rectangles.
    psi_safe = mask_psi_for_structure_safe_contours(psi, R, Z, tokamak)
    drew_core = False
    # Core nested surfaces strictly between axis and boundary (exclusive).
    if np.isfinite(psi_axis) and np.isfinite(psi_bndry) and abs(psi_bndry - psi_axis) > 0.0:
        lo, hi = (psi_axis, psi_bndry) if psi_axis < psi_bndry else (psi_bndry, psi_axis)
        # Exclude exact axis/boundary endpoints for cleaner nesting.
        core_levels = linspace(lo, hi, int(n_core_contours) + 2)[1:-1]
        if len(core_levels) > 0:
            ax.contour(
                R,
                Z,
                psi_safe,
                levels=core_levels,
                colors="0.35",
                linewidths=0.7,
                alpha=0.85,
            )
            drew_core = True
    # Honest fallback: never leave a blank plasma when ψ exists but X/O ψ
    # levels were missing after child restore (30201 inverse_equilibrium.png).
    # Prefer levels between axis and dump-LCFS mean ψ when available — never
    # spray domain-wide contours through PF coils as if they were core surfaces.
    if not drew_core and np.isfinite(psi).any() and np.isfinite(psi_axis):
        psi_edge = float("nan")
        if dump_lcfs is not None:
            try:
                rr = np.asarray(dump_lcfs[0], dtype=float).ravel()
                zz = np.asarray(dump_lcfs[1], dtype=float).ravel()
                m = np.isfinite(rr) & np.isfinite(zz)
                if int(m.sum()) >= 3:
                    r_mesh = np.asarray(eq.R, dtype=float)
                    z_mesh = np.asarray(eq.Z, dtype=float)
                    vals = []
                    for r0, z0 in zip(rr[m][:: max(1, int(m.sum()) // 40)], zz[m][:: max(1, int(m.sum()) // 40)]):
                        dist2 = (r_mesh - r0) ** 2 + (z_mesh - z0) ** 2
                        ii = int(np.nanargmin(dist2))
                        vals.append(float(psi.ravel()[ii]))
                    if vals:
                        psi_edge = float(np.median(np.asarray(vals, dtype=float)))
            except Exception:
                psi_edge = float("nan")
        if np.isfinite(psi_edge) and abs(psi_edge - psi_axis) > 0.0:
            lo, hi = (psi_axis, psi_edge) if psi_axis < psi_edge else (psi_edge, psi_axis)
            levels = linspace(lo, hi, int(n_core_contours) + 2)[1:-1]
            if len(levels) > 0:
                ax.contour(
                    R,
                    Z,
                    psi_safe,
                    levels=levels,
                    colors="0.35",
                    linewidths=0.6,
                    alpha=0.75,
                )
                drew_core = True
                if not np.isfinite(psi_bndry):
                    psi_bndry = psi_edge
    if not drew_core and np.isfinite(psi_safe).any():
        # Last resort: few muted levels on structure-safe ψ only.
        finite = psi_safe[np.isfinite(psi_safe)]
        if finite.size > 8:
            pmin, pmax = float(amin(finite)), float(amax(finite))
            if abs(pmax - pmin) > 0.0:
                levels = linspace(pmin, pmax, 8)[1:-1]
                if len(levels) > 0:
                    ax.contour(
                        R,
                        Z,
                        psi_safe,
                        levels=levels,
                        colors="0.55",
                        linewidths=0.45,
                        alpha=0.45,
                        linestyles=":",
                    )
                    drew_core = True

    # Open-field / vacuum contours outside LCFS (structure-masked).
    if show_open_field and np.isfinite(psi_bndry):
        outside = psi_safe[np.isfinite(psi_safe)]
        if psi_axis < psi_bndry:
            cand = outside[outside > psi_bndry]
        else:
            cand = outside[outside < psi_bndry]
        if cand.size > 8:
            open_levels = linspace(float(amin(cand)), float(amax(cand)), int(n_open_contours) + 2)[1:-1]
            ax.contour(
                R,
                Z,
                psi_safe,
                levels=open_levels,
                colors="0.55",
                linewidths=0.45,
                alpha=0.4,
                linestyles=":",
            )
            ax.plot(
                [],
                [],
                ":",
                color="0.55",
                lw=0.8,
                label="open-field (masked: inside limiter, not through coils)",
            )

    # Separatrix / LCFS: prefer sanitized polyline (honest closed boundary).
    # Contouring ψ=ψ_bndry draws the full isoflux including private-flux legs that
    # often snake through the solenoid on coarse grids — looks like "LCFS in coils".
    bounds = grid_bounds_from_eq(eq)
    drew_lcfs = False
    if dump_lcfs is not None:
        drew_lcfs = overlay_dump_lcfs(
            ax,
            dump_lcfs[0],
            dump_lcfs[1],
            label=str(lcfs_label or "LCFS"),
            r_min=bounds.get("Rmin"),
            r_max=bounds.get("Rmax"),
            z_min=bounds.get("Zmin"),
            z_max=bounds.get("Zmax"),
        )
    if (
        not drew_lcfs
        and allow_psi_bndry_lcfs_fallback
        and np.isfinite(psi_bndry)
    ):
        ax.contour(
            R,
            Z,
            psi_safe,
            levels=[psi_bndry],
            colors="r",
            linewidths=2.0,
            linestyles="solid",
        )
        ax.plot([], [], "r-", lw=2.0, label="LCFS (primary X ψ)")
        drew_lcfs = True
    elif drew_lcfs and np.isfinite(psi_bndry) and show_open_field:
        # Faint primary-X isoflux for divertor legs — structure-masked only.
        ax.contour(
            R,
            Z,
            psi_safe,
            levels=[psi_bndry],
            colors="r",
            linewidths=0.7,
            linestyles=":",
            alpha=0.35,
        )

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
    apply_equal_aspect_rz(ax)
    ax.grid(alpha=0.25)
    ax.set_xlabel("Major radius [m]")
    ax.set_ylabel("Height [m]")
    if not show_open_field:
        ax.plot(
            [],
            [],
            ":",
            color="0.65",
            lw=0.8,
            label="open-field omitted",
        )


def save_equilibrium_png(
    *,
    tokamak: Any,
    eq: Any,
    out_path: Path,
    title: str,
    dpi: int = 100,
    figsize: tuple[float, float] = (4.0, 8.0),
    curated: bool = True,
    plot_style: Optional[str] = None,
    constrain: Any = None,
    profiles: Any = None,
    inverse_targets: Optional[Dict[str, Any]] = None,
    run_dir: Optional[Path] = None,
    dump_lcfs: Optional[Tuple[Any, Any]] = None,
    use_inverse_dump_lcfs: bool = True,
    use_inverse_targets: bool = True,
    lcfs_label: Optional[str] = None,
) -> Path:
    """Save one equilibrium PNG frame (Agg-safe).

    Default ``plot_style=curated`` (core surfaces + LCFS). Pass
    ``plot_style='freegsnke_native'`` for example01a-style ``tokamak.plot`` +
    ``eq.plot``. When ``run_dir`` is set and flags allow, archive Inverse X/O
    targets and Inverse dump LCFS are loaded. Forward callers must pass
    ``use_inverse_dump_lcfs=False`` (and usually ``use_inverse_targets=False``)
    so Inverse separatrix is never painted on measured-PF Forward equilibria.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if inverse_targets is None and use_inverse_targets and run_dir is not None:
        inverse_targets = load_inverse_null_targets(Path(run_dir))
    if not use_inverse_targets:
        inverse_targets = None
    if dump_lcfs is None and use_inverse_dump_lcfs and run_dir is not None:
        dump_lcfs = load_dump_lcfs(Path(run_dir))
    if not use_inverse_dump_lcfs and dump_lcfs is None:
        # Explicit: do not fall back to Inverse dump when Forward supplies none.
        dump_lcfs = None

    style = str(plot_style or ("curated" if curated else "freegsnke_native")).strip().lower()
    if style not in {"freegsnke_native", "curated"}:
        style = "curated"

    label = str(lcfs_label or ("LCFS (dump polyline)" if use_inverse_dump_lcfs else "LCFS (Forward)"))
    # Forward/Evolutive: never substitute unmasked ψ=ψ_bndry (snakes through CS).
    allow_psi_fallback = bool(use_inverse_dump_lcfs)
    show_of = True
    n_open = 6
    try:
        inputs_guess = None
        if run_dir is not None:
            rd = Path(run_dir)
            for cand in (rd / "inputs", rd):
                if (cand / "presentation_authority.json").is_file():
                    inputs_guess = cand
                    break
        if inputs_guess is not None:
            pres = load_presentation_authority(inputs_guess / "presentation_authority.json")
            show_of = bool(pres.show_open_field)
            n_open = int(pres.n_open_contours)
    except Exception:
        pass

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(1, 1, figsize=figsize, dpi=dpi)
    if style == "curated":
        try:
            if profiles is not None:
                attach_profiles_after_restore(eq, profiles)
            plot_equilibrium_curated(
                ax,
                eq,
                tokamak,
                inverse_targets=inverse_targets,
                dump_lcfs=dump_lcfs,
                lcfs_label=label,
                allow_psi_bndry_lcfs_fallback=allow_psi_fallback,
                show_open_field=show_of,
                n_open_contours=n_open,
            )
        except Exception as e:
            plt.close(fig)
            raise PresentationError(f"curated plot failed: {e}") from e
    else:
        try:
            plot_equilibrium_freegsnke_native(
                ax,
                eq,
                tokamak,
                constrain=constrain,
                inverse_targets=inverse_targets,
                profiles=profiles,
            )
            # Native may omit LCFS when xpt empty — show caller polyline only.
            if dump_lcfs is not None:
                try:
                    from mast_freegsnke.freegsnke_lcfs import grid_bounds_from_eq

                    b = grid_bounds_from_eq(eq)
                    xpt = getattr(getattr(eq, "_profiles", None), "xpt", None)
                    if xpt is None or len(xpt) < 1:
                        overlay_dump_lcfs(
                            ax,
                            dump_lcfs[0],
                            dump_lcfs[1],
                            label=label,
                            r_min=b.get("Rmin"),
                            r_max=b.get("Rmax"),
                            z_min=b.get("Zmin"),
                            z_max=b.get("Zmax"),
                        )
                except Exception:
                    overlay_dump_lcfs(ax, dump_lcfs[0], dump_lcfs[1], label=label)
        except Exception as e:
            plt.close(fig)
            raise PresentationError(f"freegsnke_native plot failed: {e}") from e
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
