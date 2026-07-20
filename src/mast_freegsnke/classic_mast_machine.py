"""Build classic MAST FreeGSNKE machine pickles from FAIR-MAST Level-2 geometry.

FAIR-MAST publishes classic MAST (not MAST-U). Filament R/Z/width/height come
from ``pf_active.zarr``. The limiter/wall contour comes from ``wall.zarr``
``limiter_r``/``limiter_z`` (EFIT limiter geometry published by FAIR-MAST —
not surveyed CAD vessel). Passives stay empty: ``pf_passive.zarr`` has
parallelogram geometry but no resistivity, and inventing ρ is forbidden.
Active-coil resistivity uses the FreeGSNKE default copper value ``1.55e-8``
declared in provenance (material constant), not invented coil geometry.
"""

from __future__ import annotations

import json
import pickle
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# FreeGSNKE MAST-U / example machine files use this copper resistivity (Ω·m).
FREEGSNKE_DEFAULT_COPPER_RESISTIVITY = 1.55e-8

CLASSIC_CIRCUIT_ORDER: Tuple[str, ...] = (
    "Solenoid",
    "P2_inner",
    "P2_outer",
    "P3",
    "P4",
    "P5",
    "P6",
)

# Divertor / MAST-U-only labels that must not appear in classic production pickles.
MASTU_ONLY_CIRCUIT_PREFIXES: Tuple[str, ...] = ("D1", "D2", "D3", "Dp", "D5", "D6", "D7", "PX")

# Multi-coil FAIR-MAST array stems: upper → FreeGSNKE subcoil "1", lower → "2".
_MULTI_COIL_STEMS: Dict[str, str] = {
    "P2_inner": "p2_inner",
    "P2_outer": "p2_outer",
    "P3": "p3",
    "P4": "p4",
    "P5": "p5",
    "P6": "p6",
}


class ClassicMastMachineError(ValueError):
    pass


def _open_zarr_group(path: Path):
    path = Path(path)
    if not path.exists():
        raise ClassicMastMachineError(f"zarr path not found: {path}")
    try:
        import zarr

        return zarr.open(str(path), mode="r")
    except Exception as e_zarr:
        try:
            import xarray as xr

            return xr.open_zarr(path, consolidated=False)
        except Exception as e_xr:
            raise ClassicMastMachineError(
                f"Cannot open {path} (need zarr or xarray): zarr={e_zarr}; xarray={e_xr}"
            ) from e_xr


def _array(store, key: str) -> np.ndarray:
    if key not in store:
        raise ClassicMastMachineError(f"missing array {key!r} in store")
    raw = store[key]
    try:
        shape = tuple(getattr(raw, "shape", ()) or ())
    except Exception:
        shape = ()
    if len(shape) == 0:
        return np.asarray([raw[()]], dtype=float).ravel()
    return np.asarray(raw[:], dtype=float).ravel()


def _has(store, key: str) -> bool:
    try:
        return key in store
    except Exception:
        return False


def _zarr_attr(store, key: str, attr: str) -> Optional[str]:
    """Best-effort string attr from a zarr/xarray child array."""
    try:
        child = store[key]
        attrs = getattr(child, "attrs", None)
        if attrs is None:
            return None
        if attr in attrs:
            return str(attrs[attr])
        # zarr v3 / dict-like
        get = getattr(attrs, "get", None)
        if callable(get):
            v = get(attr)
            return None if v is None else str(v)
    except Exception:
        return None
    return None


def _filament_leaf(
    r: np.ndarray,
    z: np.ndarray,
    width: np.ndarray,
    height: np.ndarray,
    *,
    resistivity: float,
) -> Dict[str, Any]:
    m = np.isfinite(r) & np.isfinite(z)
    if not np.any(m):
        raise ClassicMastMachineError("filament pack has no finite R/Z samples")
    r_f = r[m]
    z_f = z[m]
    w = width[m] if width.size == r.size else width
    h = height[m] if height.size == r.size else height
    w_f = w[np.isfinite(w)] if w.size else np.array([])
    h_f = h[np.isfinite(h)] if h.size else np.array([])
    if w_f.size == 0 or h_f.size == 0:
        raise ClassicMastMachineError("filament pack missing finite width/height")
    return {
        "R": [float(x) for x in r_f.tolist()],
        "Z": [float(x) for x in z_f.tolist()],
        "dR": float(np.mean(w_f)),
        "dZ": float(np.mean(h_f)),
        "polarity": 1,
        "resistivity": float(resistivity),
        "multiplier": 1,
    }


def build_active_coils_from_pf_zarr(
    pf_zarr: Path,
    *,
    resistivity: float = FREEGSNKE_DEFAULT_COPPER_RESISTIVITY,
) -> Dict[str, Any]:
    """Build FreeGSNKE ``active_coils`` dict from FAIR-MAST ``pf_active.zarr``."""
    store = _open_zarr_group(pf_zarr)
    out: Dict[str, Any] = {}

    # Solenoid — single MultiCoil (top-level R/Z lists).
    sol = _filament_leaf(
        _array(store, "sol_r"),
        _array(store, "sol_z"),
        _array(store, "sol_width"),
        _array(store, "sol_height"),
        resistivity=resistivity,
    )
    out["Solenoid"] = sol

    for circuit, stem in _MULTI_COIL_STEMS.items():
        parts: Dict[str, Any] = {}
        for sub, side in (("1", "upper"), ("2", "lower")):
            r_key = f"{stem}_{side}_r"
            z_key = f"{stem}_{side}_z"
            w_key = f"{stem}_{side}_width"
            h_key = f"{stem}_{side}_height"
            for k in (r_key, z_key, w_key, h_key):
                if not _has(store, k):
                    raise ClassicMastMachineError(
                        f"circuit {circuit}: missing FAIR-MAST array {k}"
                    )
            leaf = _filament_leaf(
                _array(store, r_key),
                _array(store, z_key),
                _array(store, w_key),
                _array(store, h_key),
                resistivity=resistivity,
            )
            # Classic MAST P6 is anti-series (radial field / vertical control):
            # lower half carries opposite current to the shared circuit amp.
            if circuit == "P6" and side == "lower":
                leaf["polarity"] = -1
            parts[sub] = leaf
        out[circuit] = parts

    # Fail-closed: exact classic key set, no divertors.
    keys = list(out.keys())
    if keys != list(CLASSIC_CIRCUIT_ORDER):
        raise ClassicMastMachineError(
            f"unexpected circuit keys {keys}; expected {list(CLASSIC_CIRCUIT_ORDER)}"
        )
    return out


def limiter_from_wall_rz(
    r: Sequence[float],
    z: Sequence[float],
    *,
    comment: Optional[str] = None,
) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    """Limiter contour from FAIR-MAST ``wall.zarr`` in published vertex order.

    Points are EFIT limiter geometry (zarr attrs), not CAD vessel survey and not
    a flux-loop computational proxy. Order is preserved (polyline already closed
    in Level-2 for classic MAST).
    """
    rr = np.asarray(r, dtype=float).ravel()
    zz = np.asarray(z, dtype=float).ravel()
    if rr.size != zz.size:
        raise ClassicMastMachineError("wall limiter_r/z length mismatch")
    m = np.isfinite(rr) & np.isfinite(zz)
    rr, zz = rr[m], zz[m]
    if rr.size < 3:
        raise ClassicMastMachineError(
            f"need >=3 finite wall limiter points, got {rr.size}"
        )
    points = [{"R": float(rr[i]), "Z": float(zz[i])} for i in range(rr.size)]
    # Close the polygon if first/last differ (deterministic; no invented vertices).
    if points[0]["R"] != points[-1]["R"] or points[0]["Z"] != points[-1]["Z"]:
        points.append(dict(points[0]))
    rc = float(np.mean(rr))
    zc = float(np.mean(zz))
    comment_s = (comment or "").strip()
    meta: Dict[str, Any] = {
        "source": "wall.zarr",
        "arrays": ["limiter_r", "limiter_z"],
        "rule": "published_vertex_order_from_fairmast_wall",
        "centroid_R_m": rc,
        "centroid_Z_m": zc,
        "n_points": len(points),
        "not_cad_vessel": True,
        "provenance": (
            "FAIR-MAST Level-2 wall.zarr limiter_r/z (EFIT limiter geometry). "
            "Not surveyed CAD vessel; not a flux-loop computational contour."
            + (f" Attr comment: {comment_s}" if comment_s else "")
        ),
    }
    if comment_s:
        meta["zarr_comment"] = comment_s
    return points, meta


def build_limiter_from_wall_zarr(wall_zarr: Path) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    store = _open_zarr_group(wall_zarr)
    if not _has(store, "limiter_r") or not _has(store, "limiter_z"):
        raise ClassicMastMachineError(
            "wall.zarr missing limiter_r/z (required for classic MAST limiter/wall)"
        )
    comment = _zarr_attr(store, "limiter_r", "comment") or _zarr_attr(
        store, "limiter_z", "comment"
    )
    return limiter_from_wall_rz(
        _array(store, "limiter_r"),
        _array(store, "limiter_z"),
        comment=comment,
    )


def limiter_from_flux_loop_rz(
    r: Sequence[float],
    z: Sequence[float],
) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    """Legacy fallback only: sort flux-loop (R,Z) by poloidal angle about centroid.

    Not used for production machine_authority when wall.zarr is present. Kept for
    unit tests and explicit ``allow_flux_loop_limiter_fallback``.
    """
    rr = np.asarray(r, dtype=float).ravel()
    zz = np.asarray(z, dtype=float).ravel()
    if rr.size != zz.size:
        raise ClassicMastMachineError("flux_loop_r/z length mismatch")
    m = np.isfinite(rr) & np.isfinite(zz)
    rr, zz = rr[m], zz[m]
    if rr.size < 3:
        raise ClassicMastMachineError(
            f"need >=3 finite flux-loop points for limiter, got {rr.size}"
        )
    rc = float(np.mean(rr))
    zc = float(np.mean(zz))
    ang = np.arctan2(zz - zc, rr - rc)
    # Stable: angle primary, then R, then Z.
    order = np.lexsort((zz, rr, ang))
    points = [{"R": float(rr[i]), "Z": float(zz[i])} for i in order]
    meta = {
        "source": "magnetics.zarr",
        "arrays": ["flux_loop_r", "flux_loop_z"],
        "rule": "poloidal_angle_about_centroid_lexsort_angle_R_Z",
        "centroid_R_m": rc,
        "centroid_Z_m": zc,
        "n_points": len(points),
        "not_cad_vessel": True,
        "fallback": True,
        "provenance": (
            "FALLBACK computational limiter from FAIR-MAST flux-loop geometry "
            "channels (magnetics.zarr flux_loop_r/z). Not EFIT wall.limiter and "
            "not surveyed vessel CAD."
        ),
    }
    return points, meta


def build_limiter_from_magnetics_zarr(mag_zarr: Path) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    store = _open_zarr_group(mag_zarr)
    if not _has(store, "flux_loop_r") or not _has(store, "flux_loop_z"):
        raise ClassicMastMachineError(
            "magnetics.zarr missing flux_loop_r/z (flux-loop limiter fallback)"
        )
    return limiter_from_flux_loop_rz(_array(store, "flux_loop_r"), _array(store, "flux_loop_z"))


def pf_passive_omission_note(shot_cache: Path) -> Dict[str, Any]:
    """Record why FreeGSNKE passives are empty despite FAIR-MAST pf_passive geometry."""
    pp = Path(shot_cache) / "pf_passive.zarr"
    note = {
        "passives_written": [],
        "reason": (
            "FAIR-MAST Level-2 pf_passive publishes parallelogram geometry "
            "(r/z/width/height/shapeAngle1/shapeAngle2) but no resistivity; "
            "FreeGSNKE passive pickles require resistivity. Do not invent resistivity — "
            "passive_coils.pickle stays empty."
        ),
        "pf_passive_zarr_present": pp.exists(),
    }
    if not pp.exists():
        note["hint"] = (
            "Optional: download group pf_passive for audit; still cannot build "
            "passives without a published resistivity authority."
        )
        return note
    try:
        store = _open_zarr_group(pp)
        try:
            keys = list(store.keys())
        except Exception:
            keys = list(store)
        comps = sorted({k[:-2] for k in keys if str(k).endswith("_r")})
        note["geometry_components"] = comps
        resist_like = [
            k
            for k in keys
            if any(tok in str(k).lower() for tok in ("resist", "ohm", "eta", "rho"))
        ]
        note["resistivity_keys_found"] = resist_like
    except Exception as e:
        note["inspect_error"] = f"{type(e).__name__}: {e}"
    return note


def _archive_mastu_pickles(machine_dir: Path, archive_dir: Path) -> List[str]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    moved: List[str] = []
    for name in (
        "active_coils.pickle",
        "passive_coils.pickle",
        "limiter.pickle",
        "wall.pickle",
        "FREEGSNKE_MACHINE_PROVENANCE.json",
    ):
        src = machine_dir / name
        if src.exists():
            dst = archive_dir / name
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))
            moved.append(name)
    return moved


def write_classic_mast_machine(
    shot_cache: Path,
    out_dir: Path,
    *,
    shot: Optional[int] = None,
    archive_mastu: bool = True,
    resistivity: float = FREEGSNKE_DEFAULT_COPPER_RESISTIVITY,
    validate_tokamak: bool = False,
    allow_flux_loop_limiter_fallback: bool = False,
) -> Dict[str, Any]:
    """Write classic MAST FreeGSNKE pickles into ``out_dir`` (production machine_authority)."""
    shot_cache = Path(shot_cache)
    out_dir = Path(out_dir)
    pf = shot_cache / "pf_active.zarr"
    wall_zarr = shot_cache / "wall.zarr"
    mag = shot_cache / "magnetics.zarr"
    if not pf.exists():
        raise ClassicMastMachineError(f"Need pf_active.zarr under {shot_cache}")

    out_dir.mkdir(parents=True, exist_ok=True)
    archived: List[str] = []
    if archive_mastu:
        archived = _archive_mastu_pickles(out_dir, out_dir / "archive_mastu_like")

    active = build_active_coils_from_pf_zarr(pf, resistivity=resistivity)

    if wall_zarr.exists():
        limiter, lim_meta = build_limiter_from_wall_zarr(wall_zarr)
    elif allow_flux_loop_limiter_fallback and mag.exists():
        limiter, lim_meta = build_limiter_from_magnetics_zarr(mag)
    else:
        raise ClassicMastMachineError(
            f"Need wall.zarr under {shot_cache} (FAIR-MAST Level-2 wall limiter from EFIT). "
            "Flux-loop contours are not the production vessel limiter "
            "(pass allow_flux_loop_limiter_fallback=True only for legacy caches)."
        )

    wall = list(limiter)  # FreeGSNKE wall; same EFIT limiter contour (not CAD)
    passives: List[Any] = []
    passive_note = pf_passive_omission_note(shot_cache)

    (out_dir / "active_coils.pickle").write_bytes(pickle.dumps(active, protocol=4))
    (out_dir / "limiter.pickle").write_bytes(pickle.dumps(limiter, protocol=4))
    (out_dir / "wall.pickle").write_bytes(pickle.dumps(wall, protocol=4))
    (out_dir / "passive_coils.pickle").write_bytes(pickle.dumps(passives, protocol=4))

    provenance = {
        "machine": "classic_MAST",
        "source": "FAIR-MAST Level-2 Zarr (classic MAST — not MAST-U)",
        "source_repo": "https://github.com/ukaea/fair-mast",
        "shot_cache": str(shot_cache),
        "shot": shot,
        "files": [
            "active_coils.pickle",
            "limiter.pickle",
            "wall.pickle",
            "passive_coils.pickle",
        ],
        "active_circuits": list(CLASSIC_CIRCUIT_ORDER),
        "filament_geometry": (
            "R/Z filament lists and mean width/height (dR/dZ) from pf_active.zarr "
            "arrays (sol_*, p2_inner_*, p2_outer_*, p3_*, p4_*, p5_*, p6_*)."
        ),
        "resistivity_ohm_m": resistivity,
        "resistivity_citation": (
            "FreeGSNKE default copper resistivity used in public machine_configs "
            f"(value {resistivity}); material constant — not invented coil geometry. "
            "FAIR-MAST Level-2 pf_active does not publish coil resistivity."
        ),
        "polarity": (
            "+1 for all filaments except P6 lower (polarity=-1; classic MAST anti-series vertical control)"
        ),
        "limiter": lim_meta,
        "wall": (
            "set equal to wall.zarr limiter contour (EFIT limiter geometry; not CAD vessel)"
            if lim_meta.get("source") == "wall.zarr"
            else "set equal to fallback flux-loop limiter (not CAD vessel)"
        ),
        "passives": passive_note,
        "honest_limits": [
            "Limiter/wall = FAIR-MAST wall.zarr EFIT limiter != surveyed CAD vessel",
            "No FreeGSNKE passives: pf_passive geometry exists but resistivity is unpublished",
            "P3/P6: no usable measured FAIR-MAST PF voltage in public L1/L2 (see configs/l1_voltage_inventory_30201.json); evolutive uses I*R only",
            f"Active-coil resistivity = FreeGSNKE copper default {resistivity} (declared material constant)",
        ],
        "note": (
            "Replaces FreeGSNKE public MAST-U-like structural pickles for FAIR-MAST "
            "classic MAST shots. Archived prior pickles under archive_mastu_like/ when present."
        ),
    }
    try:
        from .honest_limits import shot_cache_machine_fingerprints

        fps = shot_cache_machine_fingerprints(shot_cache)
        provenance["source_fingerprints"] = {
            "wall": fps.get("wall"),
            "pf_active": fps.get("pf_active"),
        }
    except Exception as e:
        provenance["source_fingerprints_error"] = f"{type(e).__name__}: {e}"

    (out_dir / "FREEGSNKE_MACHINE_PROVENANCE.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report: Dict[str, Any] = {
        "ok": True,
        "out_dir": str(out_dir),
        "circuits": list(CLASSIC_CIRCUIT_ORDER),
        "n_limiter_points": len(limiter),
        "limiter_meta": lim_meta,
        "passives": passive_note,
        "archived_mastu_like": archived,
        "resistivity_ohm_m": resistivity,
    }

    if validate_tokamak:
        report["tokamak_validation"] = validate_classic_tokamak(out_dir)

    return report


def validate_classic_tokamak(
    machine_dir: Path,
    *,
    magnetic_probe_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Load pickles with ``freegsnke.build_machine.tokamak`` (fail-closed)."""
    machine_dir = Path(machine_dir)
    try:
        from freegsnke.build_machine import tokamak
    except ImportError as e:
        return {
            "ok": False,
            "skipped": True,
            "error": f"freegsnke not importable: {e}",
        }

    kwargs: Dict[str, Any] = {
        "active_coils_path": str(machine_dir / "active_coils.pickle"),
        "limiter_path": str(machine_dir / "limiter.pickle"),
        "passive_coils_path": str(machine_dir / "passive_coils.pickle"),
        "wall_path": str(machine_dir / "wall.pickle"),
    }
    if magnetic_probe_path is not None and Path(magnetic_probe_path).exists():
        kwargs["magnetic_probe_path"] = str(magnetic_probe_path)

    try:
        tok = tokamak(**kwargs)
    except Exception as e:
        return {"ok": False, "skipped": False, "error": f"{type(e).__name__}: {e}"}

    # Circuit names from FreeGSNKE / FreeGS4E tokamak coils list when available.
    names: List[str] = []
    coils = getattr(tok, "coils", None)
    if coils is not None:
        for item in coils:
            if isinstance(item, (tuple, list)) and item:
                names.append(str(item[0]))
            elif hasattr(item, "name"):
                names.append(str(item.name))

    with open(machine_dir / "active_coils.pickle", "rb") as f:
        active = pickle.load(f)
    keys = list(active.keys()) if isinstance(active, dict) else []
    bad = [k for k in keys if k in MASTU_ONLY_CIRCUIT_PREFIXES or str(k).startswith("D")]
    ok = keys == list(CLASSIC_CIRCUIT_ORDER) and not bad
    return {
        "ok": ok,
        "skipped": False,
        "active_keys": keys,
        "tokamak_coil_names": names,
        "mastu_labels_present": bad,
    }


def load_active_circuit_keys(machine_dir: Path) -> List[str]:
    p = Path(machine_dir) / "active_coils.pickle"
    if not p.exists():
        return []
    with open(p, "rb") as f:
        active = pickle.load(f)
    if not isinstance(active, dict):
        return []
    return [str(k) for k in active.keys()]
