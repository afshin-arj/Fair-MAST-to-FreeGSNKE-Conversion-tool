"""Build machine authority artifacts from FAIR-MAST Level-2 Zarr (authoritative metrology).

Does not invent probe positions: values are read from magnetics/pf_active geometry arrays.
Orientation vectors for pickups are assigned from MAST probe-name conventions and recorded
in metadata (not from silent defaults inside FreeGSNKE).

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def _as_str_list(vals) -> List[str]:
    out: List[str] = []
    for v in vals:
        if isinstance(v, bytes):
            out.append(v.decode("utf-8", errors="replace"))
        else:
            out.append(str(v))
    return out


def _orientation_from_name(name: str) -> Tuple[str, List[float]]:
    """Deterministic orientation from MAST probe family naming."""
    n = name.lower()
    if "obr" in n:  # outer board radial
        return "radial", [1.0, 0.0, 0.0]
    if any(tok in n for tok in ("obv", "omv", "ccbv")):  # vertical poloidal
        return "normal", [0.0, 0.0, 1.0]
    if "tor" in n or n.startswith("cc") and "pol" not in n:
        return "toroidal", [0.0, 1.0, 0.0]
    # Default poloidal-normal for unnamed pol probes
    return "normal", [0.0, 0.0, 1.0]


def build_probe_geometry_from_magnetics_zarr(mag_zarr: Path) -> Dict[str, Any]:
    import xarray as xr

    ds = xr.open_zarr(mag_zarr, consolidated=False)
    flux_loops: List[Dict[str, Any]] = []
    if "flux_loop_r" in ds and "flux_loop_z" in ds:
        names = _as_str_list(ds["flux_loop_geometry_channel"].values) if "flux_loop_geometry_channel" in ds.coords else [
            f"FL_{i:03d}" for i in range(len(ds["flux_loop_r"]))
        ]
        r = np.asarray(ds["flux_loop_r"].values, dtype=float)
        z = np.asarray(ds["flux_loop_z"].values, dtype=float)
        for i, name in enumerate(names):
            if i >= len(r):
                break
            if not np.isfinite(r[i]) or not np.isfinite(z[i]):
                continue
            flux_loops.append({"name": name, "r_m": float(r[i]), "z_m": float(z[i]), "turns": 1})

    pickup_coils: List[Dict[str, Any]] = []
    families = [
        ("b_field_pol_probe_obr", "b_field_pol_probe_obr_geometry_channel"),
        ("b_field_pol_probe_obv", "b_field_pol_probe_obv_geometry_channel"),
        ("b_field_pol_probe_omv", "b_field_pol_probe_omv_geometry_channel"),
        ("b_field_pol_probe_ccbv", "b_field_pol_probe_ccbv_geometry_channel"),
        ("b_field_pol_probe_cc", "b_field_pol_probe_cc_geometry_channel"),
        ("b_field_tor_probe_cc", "b_field_tor_probe_cc_geometry_channel"),
    ]
    for prefix, geom_coord in families:
        r_key, z_key, phi_key = f"{prefix}_r", f"{prefix}_z", f"{prefix}_phi"
        # some families use phi_1
        if phi_key not in ds and f"{prefix}_phi_1" in ds:
            phi_key = f"{prefix}_phi_1"
        if r_key not in ds or z_key not in ds:
            continue
        names = _as_str_list(ds[geom_coord].values) if geom_coord in ds.coords else [
            f"{prefix}_{i:03d}" for i in range(len(ds[r_key]))
        ]
        r = np.asarray(ds[r_key].values, dtype=float)
        z = np.asarray(ds[z_key].values, dtype=float)
        if phi_key in ds:
            phi = np.asarray(ds[phi_key].values, dtype=float)
        else:
            phi = np.zeros_like(r)
        for i, name in enumerate(names):
            if i >= len(r):
                break
            if not (np.isfinite(r[i]) and np.isfinite(z[i])):
                continue
            orient, nvec = _orientation_from_name(name if "obr" in prefix or "obv" in prefix or "omv" in prefix or "ccbv" in prefix else prefix)
            # Prefer family token for orientation when name alone is ambiguous
            if "obr" in prefix:
                orient, nvec = "radial", [1.0, 0.0, 0.0]
            elif any(t in prefix for t in ("obv", "omv", "ccbv")):
                orient, nvec = "normal", [0.0, 0.0, 1.0]
            elif "tor" in prefix:
                orient, nvec = "toroidal", [0.0, 1.0, 0.0]
            pickup_coils.append(
                {
                    "name": str(name).upper(),
                    "r_m": float(r[i]),
                    "phi_deg": float(phi[i]) if np.isfinite(phi[i]) else 0.0,
                    "z_m": float(z[i]),
                    "n_r": nvec[0],
                    "n_phi": nvec[1],
                    "n_z": nvec[2],
                    "orientation": orient,
                }
            )

    return {
        "schema_version": "1.0",
        "notes": (
            "Built from FAIR-MAST Level-2 magnetics.zarr geometry arrays. "
            "Pickup orientation_vector assigned from probe-family naming conventions "
            "(obr=radial, obv/omv/ccbv=normal/Z, tor=toroidal)."
        ),
        "flux_loops": flux_loops,
        "pickup_coils": pickup_coils,
        "metadata": {
            "source": "FAIR-MAST Level-2 magnetics.zarr",
            "orientation_policy": "probe_family_name_convention_v1",
            "n_flux_loops": len(flux_loops),
            "n_pickups": len(pickup_coils),
        },
    }


def build_coil_geometry_from_pf_zarr(pf_zarr: Path) -> Dict[str, Any]:
    import xarray as xr

    ds = xr.open_zarr(pf_zarr, consolidated=False)
    coils: List[Dict[str, Any]] = []
    # Centroid of filament packs when r/z arrays exist
    pairs = [
        ("P2_inner", ["p2_inner_lower_r", "p2_inner_upper_r"], ["p2_inner_lower_z", "p2_inner_upper_z"]),
        ("P2_outer", ["p2_outer_lower_r", "p2_outer_upper_r"], ["p2_outer_lower_z", "p2_outer_upper_z"]),
        ("P3", ["p3_lower_r", "p3_upper_r"], ["p3_lower_z", "p3_upper_z"]),
        ("P4", ["p4_lower_r", "p4_upper_r"], ["p4_lower_z", "p4_upper_z"]),
        ("P5", ["p5_lower_r", "p5_upper_r"], ["p5_lower_z", "p5_upper_z"]),
        ("P6", ["p6_lower_r", "p6_upper_r"], ["p6_lower_z", "p6_upper_z"]),
        ("Solenoid", ["sol_r"], ["sol_z"]),
    ]
    for coil, rkeys, zkeys in pairs:
        rs: List[float] = []
        zs: List[float] = []
        for rk, zk in zip(rkeys, zkeys):
            if rk in ds and zk in ds:
                rv = np.asarray(ds[rk].values, dtype=float).ravel()
                zv = np.asarray(ds[zk].values, dtype=float).ravel()
                m = np.isfinite(rv) & np.isfinite(zv)
                rs.extend(rv[m].tolist())
                zs.extend(zv[m].tolist())
        if not rs:
            continue
        coils.append(
            {
                "coil": coil,
                "r_m": float(np.mean(rs)),
                "z_m": float(np.mean(zs)),
                "n_filaments": len(rs),
                "units": "A",
                "source_arrays": rkeys + zkeys,
            }
        )
    return {
        "schema_version": "1.0",
        "notes": "Coil centroids derived from FAIR-MAST pf_active.zarr filament r/z arrays (mean of finite samples).",
        "coils": coils,
    }


def write_machine_authority_from_shot_cache(
    shot_cache: Path,
    out_dir: Path,
    *,
    shot: Optional[int] = None,
) -> Dict[str, Any]:
    """Write machine_authority JSON bundle from a downloaded FAIR-MAST shot cache."""
    mag = shot_cache / "magnetics.zarr"
    pf = shot_cache / "pf_active.zarr"
    if not mag.exists() or not pf.exists():
        raise FileNotFoundError(f"Need magnetics.zarr and pf_active.zarr under {shot_cache}")

    out_dir.mkdir(parents=True, exist_ok=True)
    probe = build_probe_geometry_from_magnetics_zarr(mag)
    coil = build_coil_geometry_from_pf_zarr(pf)

    (out_dir / "probe_geometry.json").write_text(json.dumps(probe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "coil_geometry.json").write_text(json.dumps(coil, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    registry = {
        "schema_version": "1.0",
        "diagnostics": [
            {"name": fl["name"], "dtype": "flux_loop"} for fl in probe["flux_loops"]
        ]
        + [{"name": pc["name"], "dtype": "pickup"} for pc in probe["pickup_coils"]],
    }
    (out_dir / "diagnostic_registry.json").write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": "1.0",
        "authority_name": "MAST_FAIRMAST_Level2_MachineAuthority",
        "authority_version": "1.0.0-fairmast",
        "provenance": {
            "source": "FAIR-MAST Level-2 Zarr",
            "source_repo": "https://github.com/ukaea/mast-data",
            "source_commit": "n/a-level2-archive",
            "metrology_reference": "magnetics.zarr + pf_active.zarr geometry arrays",
            "shot_cache": str(shot_cache),
            "shot": shot,
        },
        "files": {
            "probe_geometry": "probe_geometry.json",
            "coil_geometry": "coil_geometry.json",
            "diagnostic_registry": "diagnostic_registry.json",
        },
    }
    (out_dir / "authority_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "out_dir": str(out_dir),
        "n_flux_loops": len(probe["flux_loops"]),
        "n_pickups": len(probe["pickup_coils"]),
        "n_coils": len(coil["coils"]),
    }
