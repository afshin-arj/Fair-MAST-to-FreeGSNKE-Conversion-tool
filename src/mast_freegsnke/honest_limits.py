"""Honest FAIR-MAST → FreeGSNKE limits + machine cache fingerprints.

Used by doctor banners, pipeline machine rebuild, and provenance.
Never invents metrology: fingerprints only hash published Level-2 arrays.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Arrays that define production classic MAST structural pickles.
WALL_FINGERPRINT_KEYS: Tuple[str, ...] = ("limiter_r", "limiter_z")

PF_ACTIVE_FINGERPRINT_SUFFIXES: Tuple[str, ...] = ("_r", "_z", "_width", "_height")

DEFAULT_HONEST_LIMITS: Tuple[str, ...] = (
    "Limiter/wall = FAIR-MAST wall.zarr EFIT limiter != surveyed CAD vessel",
    "No FreeGSNKE passives: pf_passive geometry exists but resistivity is unpublished",
    "P3/P6 have no measured FAIR-MAST voltage (evolutive uses I*R only)",
    "Active-coil resistivity = FreeGSNKE copper default 1.55e-08 (declared material constant)",
)


def load_honest_limits(machine_dir: Path) -> List[str]:
    """Load honest_limits from FREEGSNKE_MACHINE_PROVENANCE.json, or defaults."""
    prov = Path(machine_dir) / "FREEGSNKE_MACHINE_PROVENANCE.json"
    if prov.exists():
        try:
            obj = json.loads(prov.read_text(encoding="utf-8"))
            lim = obj.get("honest_limits")
            if isinstance(lim, list) and lim:
                return [str(x) for x in lim]
        except Exception:
            pass
    return list(DEFAULT_HONEST_LIMITS)


def honest_limits_status_lines(machine_dir: Optional[Path] = None) -> List[str]:
    """Doctor / run banner lines for declared honest limits."""
    limits = load_honest_limits(machine_dir) if machine_dir is not None else list(DEFAULT_HONEST_LIMITS)
    lines = ["[INFO] Honest limits (FAIR-MAST -> FreeGSNKE):"]
    for item in limits:
        lines.append(f"  - {item}")
    return lines


def _open_zarr(path: Path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    try:
        import zarr

        return zarr.open(str(path), mode="r")
    except Exception as e_zarr:
        try:
            import xarray as xr

            return xr.open_zarr(path, consolidated=False)
        except Exception as e_xr:
            raise RuntimeError(f"Cannot open {path}: zarr={e_zarr}; xarray={e_xr}") from e_xr


def _array_bytes(store, key: str) -> bytes:
    raw = store[key]
    try:
        shape = tuple(getattr(raw, "shape", ()) or ())
    except Exception:
        shape = ()
    if len(shape) == 0:
        arr = np.asarray(raw[()])
    else:
        arr = np.asarray(raw[:])
    # Stable fingerprint: name + dtype + shape + raw bytes (float64 view when numeric).
    if np.issubdtype(arr.dtype, np.number):
        arr = np.ascontiguousarray(arr, dtype=np.float64)
    else:
        arr = np.ascontiguousarray(arr)
    return arr.tobytes()


def fingerprint_zarr_arrays(zarr_path: Path, keys: Sequence[str]) -> str:
    """SHA-256 over selected arrays in a Level-2 group (deterministic)."""
    store = _open_zarr(zarr_path)
    h = hashlib.sha256()
    for key in sorted(keys):
        try:
            present = key in store
        except Exception:
            present = False
        if not present:
            continue
        h.update(key.encode("utf-8"))
        h.update(b"\0")
        h.update(_array_bytes(store, key))
        h.update(b"\0")
    return h.hexdigest()


def pf_active_geometry_keys(store) -> List[str]:
    try:
        names = list(store.keys())
    except Exception:
        names = list(store)
    out: List[str] = []
    for k in names:
        sk = str(k)
        if any(sk.endswith(suf) for suf in PF_ACTIVE_FINGERPRINT_SUFFIXES):
            out.append(sk)
    return sorted(out)


def shot_cache_machine_fingerprints(shot_cache: Path) -> Dict[str, Any]:
    """Fingerprints for wall limiter + pf_active filament geometry under a shot cache."""
    shot_cache = Path(shot_cache)
    out: Dict[str, Any] = {"shot_cache": str(shot_cache)}
    wall = shot_cache / "wall.zarr"
    pf = shot_cache / "pf_active.zarr"
    if wall.exists():
        out["wall"] = {
            "path": str(wall),
            "sha256": fingerprint_zarr_arrays(wall, WALL_FINGERPRINT_KEYS),
            "keys": list(WALL_FINGERPRINT_KEYS),
        }
    else:
        out["wall"] = {"path": str(wall), "sha256": None, "missing": True}
    if pf.exists():
        store = _open_zarr(pf)
        keys = pf_active_geometry_keys(store)
        out["pf_active"] = {
            "path": str(pf),
            "sha256": fingerprint_zarr_arrays(pf, keys),
            "keys": keys,
        }
    else:
        out["pf_active"] = {"path": str(pf), "sha256": None, "missing": True}
    return out


def provenance_fingerprints(machine_dir: Path) -> Optional[Dict[str, Any]]:
    prov = Path(machine_dir) / "FREEGSNKE_MACHINE_PROVENANCE.json"
    if not prov.exists():
        return None
    try:
        obj = json.loads(prov.read_text(encoding="utf-8"))
    except Exception:
        return None
    fp = obj.get("source_fingerprints")
    return fp if isinstance(fp, dict) else None


def machine_needs_rebuild(shot_cache: Path, machine_dir: Path) -> Tuple[bool, Dict[str, Any]]:
    """True when production pickles are missing fingerprints or disagree with shot cache."""
    report: Dict[str, Any] = {"shot_cache": str(shot_cache), "machine_dir": str(machine_dir)}
    required = [
        Path(machine_dir) / "active_coils.pickle",
        Path(machine_dir) / "limiter.pickle",
        Path(machine_dir) / "wall.pickle",
        Path(machine_dir) / "passive_coils.pickle",
        Path(machine_dir) / "FREEGSNKE_MACHINE_PROVENANCE.json",
    ]
    missing_files = [str(p.name) for p in required if not p.exists()]
    if missing_files:
        report["reason"] = "missing_machine_files"
        report["missing_files"] = missing_files
        return True, report

    current = shot_cache_machine_fingerprints(shot_cache)
    prior = provenance_fingerprints(machine_dir)
    report["current"] = current
    report["prior"] = prior
    if prior is None:
        report["reason"] = "provenance_missing_source_fingerprints"
        return True, report

    for group in ("wall", "pf_active"):
        cur = (current.get(group) or {}).get("sha256")
        old = (prior.get(group) or {}).get("sha256")
        if not cur:
            report["reason"] = f"{group}_fingerprint_unavailable"
            return True, report
        if cur != old:
            report["reason"] = f"{group}_fingerprint_mismatch"
            return True, report

    # Prefer wall-sourced limiter (not flux-loop fallback).
    try:
        prov = json.loads(
            (Path(machine_dir) / "FREEGSNKE_MACHINE_PROVENANCE.json").read_text(encoding="utf-8")
        )
        lim = prov.get("limiter") or {}
        if lim.get("source") != "wall.zarr":
            report["reason"] = "limiter_not_from_wall_zarr"
            return True, report
    except Exception as e:
        report["reason"] = f"provenance_unreadable:{type(e).__name__}"
        return True, report

    report["reason"] = "up_to_date"
    return False, report


def optional_group_audit_line(shot_cache: Optional[Path], group: str = "pf_passive") -> str:
    """Banner for optional audit groups (best-effort download)."""
    if shot_cache is None:
        return (
            f"[INFO] optional group {group}: not checked yet "
            "(downloaded best-effort for audit; FreeGSNKE passives still need resistivity authority)"
        )
    z = Path(shot_cache) / f"{group}.zarr"
    if z.is_dir() and any(p.is_file() for p in z.rglob("*")):
        return (
            f"[INFO] optional {group}.zarr present under {shot_cache.name} "
            "(audit only — no FreeGSNKE passives without published resistivity)"
        )
    return (
        f"[INFO] optional {group}.zarr absent "
        "(configure optional_groups to download for audit; passives stay empty without resistivity)"
    )
