"""Optional FreeGSNKE → TORAX GEQDSK geometry export (ADR-001).

Default off. When enabled, requires a snapshotted authority with declared
``rcentr_m`` (never silently use freegs4e's hardcoded R0=1.0). Profiles in the
EQDSK are parametric ``ConstrainPaxisIp`` closure — labeled, not measured kinetics.
Does not run TORAX.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional, TextIO


class ToraxGeometryExportError(ValueError):
    pass


@dataclass(frozen=True)
class ToraxGeometryExportAuthority:
    authority_name: str = "torax_geometry_export"
    authority_version: str = "1.0"
    source: str = "freegsnke_inverse_equilibrium"
    format: str = "geqdsk"
    writer: str = "mast_freegsnke.torax_geometry_export.write_geqdsk_declared_rcentr"
    timeslices: str = "t0_inverse_only"
    output_relpath: str = "downstream/torax/geqdsk_t0.eqdsk"
    label_template: str = "MAST shot {shot} FreeGSNKE inverse t0={t0:.6f}s"
    rcentr_m: float = 0.0
    rcentr_source: str = ""
    cocos_declared: str = ""
    cocos_note: str = (
        "Declared FreeGS/freegs4e-native GEQDSK convention label for documentation only; "
        "no automatic COCOS conversion. Confirm against TORAX ingest expectations."
    )
    profile_provenance: str = "execution_authority.ConstrainPaxisIp"
    profile_note: str = (
        "p/f profiles in this EQDSK are parametric GS closure knobs from the inverse "
        "execution authority — not measured kinetic profiles. TORAX transport ICs need "
        "separate authority when available."
    )
    forbid_chease: bool = True
    forbid_invented_kinetic_profiles: bool = True
    notes: str = "ADR-001 optional geometry export only; does not execute TORAX."

    def validate(self) -> None:
        if not self.authority_name.strip():
            raise ToraxGeometryExportError("authority_name required")
        if self.source != "freegsnke_inverse_equilibrium":
            raise ToraxGeometryExportError(
                f"unsupported source {self.source!r} "
                "(v1 only freegsnke_inverse_equilibrium; cited EFIT path is future work)"
            )
        if self.format != "geqdsk":
            raise ToraxGeometryExportError(
                f"unsupported format {self.format!r} (CHEASE forbidden until a real writer exists)"
            )
        if self.forbid_chease is not True:
            raise ToraxGeometryExportError("forbid_chease must be true")
        if self.timeslices != "t0_inverse_only":
            raise ToraxGeometryExportError(
                f"unsupported timeslices {self.timeslices!r} (v1: t0_inverse_only)"
            )
        if not (isinstance(self.rcentr_m, (int, float)) and float(self.rcentr_m) > 0.0):
            raise ToraxGeometryExportError(
                "rcentr_m must be a declared float > 0 "
                "(refuse freegs4e silent R0=1.0; set classic MAST / EFIT R0 in authority)"
            )
        if not str(self.rcentr_source).strip():
            raise ToraxGeometryExportError(
                "rcentr_source required (cite device/EFIT authority for rcentr_m)"
            )
        if self.cocos_declared is None or str(self.cocos_declared).strip() == "":
            raise ToraxGeometryExportError(
                "cocos_declared required (label FreeGS export convention; no silent default)"
            )
        if not str(self.output_relpath).strip():
            raise ToraxGeometryExportError("output_relpath required")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_torax_geometry_export_authority(path: Path) -> ToraxGeometryExportAuthority:
    if not path.exists():
        raise ToraxGeometryExportError(f"missing torax geometry export authority: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ToraxGeometryExportError("authority root must be an object")
    auth = ToraxGeometryExportAuthority(
        authority_name=str(obj.get("authority_name", "torax_geometry_export")),
        authority_version=str(obj.get("authority_version", "1.0")),
        source=str(obj.get("source", "freegsnke_inverse_equilibrium")),
        format=str(obj.get("format", "geqdsk")),
        writer=str(
            obj.get(
                "writer",
                "mast_freegsnke.torax_geometry_export.write_geqdsk_declared_rcentr",
            )
        ),
        timeslices=str(obj.get("timeslices", "t0_inverse_only")),
        output_relpath=str(obj.get("output_relpath", "downstream/torax/geqdsk_t0.eqdsk")),
        label_template=str(
            obj.get("label_template", "MAST shot {shot} FreeGSNKE inverse t0={t0:.6f}s")
        ),
        rcentr_m=float(obj["rcentr_m"]) if obj.get("rcentr_m") is not None else 0.0,
        rcentr_source=str(obj.get("rcentr_source", "")),
        cocos_declared=str(obj.get("cocos_declared", "")),
        cocos_note=str(obj.get("cocos_note", ToraxGeometryExportAuthority.cocos_note)),
        profile_provenance=str(
            obj.get("profile_provenance", "execution_authority.ConstrainPaxisIp")
        ),
        profile_note=str(obj.get("profile_note", ToraxGeometryExportAuthority.profile_note)),
        forbid_chease=bool(obj.get("forbid_chease", True)),
        forbid_invented_kinetic_profiles=bool(
            obj.get("forbid_invented_kinetic_profiles", True)
        ),
        notes=str(obj.get("notes", ToraxGeometryExportAuthority.notes)),
    )
    auth.validate()
    return auth


def write_torax_geometry_export_authority(
    inputs_dir: Path, auth: ToraxGeometryExportAuthority
) -> Path:
    auth.validate()
    out_dir = Path(inputs_dir) / "torax_geometry_export_authority"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "torax_geometry_export_authority.json"
    out.write_text(json.dumps(auth.to_dict(), indent=2) + "\n", encoding="utf-8")
    return out


def try_load_torax_geometry_export_authority(
    inputs_dir: Path,
) -> Optional[ToraxGeometryExportAuthority]:
    path = Path(inputs_dir) / "torax_geometry_export_authority" / "torax_geometry_export_authority.json"
    if not path.exists():
        return None
    return load_torax_geometry_export_authority(path)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_geqdsk_declared_rcentr(
    eq: Any,
    fh: TextIO,
    *,
    rcentr_m: float,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Write GEQDSK using freegs4e machinery but **declared** rcentr (not R0=1.0)."""
    import numpy as np
    from freegs4e import critical
    from freegs4e import _geqdsk
    from numpy import linspace, zeros

    rcentr = float(rcentr_m)
    if not (rcentr > 0.0):
        raise ToraxGeometryExportError("rcentr_m must be > 0")

    psi = eq.psi()
    nx, ny = psi.shape
    opoint, xpoint = critical.find_critical(eq.R, eq.Z, psi)
    if not opoint:
        raise ToraxGeometryExportError("critical.find_critical returned no O-point")
    if not xpoint:
        raise ToraxGeometryExportError("critical.find_critical returned no X-point")

    rmin, rmax = float(eq.Rmin), float(eq.Rmax)
    zmin, zmax = float(eq.Zmin), float(eq.Zmax)
    fvac = float(eq.fvac())

    data: Dict[str, Any] = {
        "nx": nx,
        "ny": ny,
        "rdim": rmax - rmin,
        "zdim": zmax - zmin,
        "rcentr": rcentr,
        "bcentr": fvac / rcentr,
        "rleft": rmin,
        "zmid": 0.5 * (zmin + zmax),
    }
    data["rmagx"], data["zmagx"], data["simagx"] = opoint[0]
    data["sibdry"] = xpoint[0][2] - data["simagx"]
    data["cpasma"] = float(eq.plasmaCurrent())

    psinorm = linspace(0.0, 1.0, nx, endpoint=False)
    data["fpol"] = eq.fpol(psinorm)
    data["pres"] = eq.pressure(psinorm)
    data["ffprime"] = eq.ffprime(psinorm)
    data["pprime"] = eq.pprime(psinorm)
    data["fprim"] = eq.ffprime(psinorm)
    data["pprim"] = eq.pprime(psinorm)
    data["psi"] = psi - data["simagx"]
    data["simagx"] = 0.0

    qpsi = zeros([nx])
    qpsi[1:] = eq.q(psinorm[1:])
    qpsi[0] = qpsi[1]
    data["qpsi"] = qpsi

    if getattr(eq.tokamak, "wall", None) is not None:
        data["rlim"] = eq.tokamak.wall.R
        data["zlim"] = eq.tokamak.wall.Z

    isoflux = np.array(eq.separatrix(ntheta=101))
    ind = int(np.argmin(isoflux[:, 1]))
    data["rbdry"] = np.roll(isoflux[:, 0][::-1], -ind)
    data["rbdry"] = np.append(data["rbdry"], data["rbdry"][0])
    data["zbdry"] = np.roll(isoflux[:, 1][::-1], -ind)
    data["zbdry"] = np.append(data["zbdry"], data["zbdry"][0])

    _geqdsk.write(data, fh, label=label)
    return {
        "rcentr_m": rcentr,
        "bcentr_T": float(fvac / rcentr),
        "fvac": fvac,
        "nx": int(nx),
        "ny": int(ny),
        "cpasma_A": float(data["cpasma"]),
    }


def export_torax_geqdsk_from_equilibrium(
    run_dir: Path,
    eq: Any,
    auth: ToraxGeometryExportAuthority,
    *,
    shot: Optional[int] = None,
    t0: Optional[float] = None,
) -> Dict[str, Any]:
    """Write GEQDSK + export_manifest.json under the run directory."""
    auth.validate()
    run_dir = Path(run_dir)
    out_path = run_dir / auth.output_relpath
    out_path.parent.mkdir(parents=True, exist_ok=True)

    label = auth.label_template.format(
        shot=int(shot) if shot is not None else -1,
        t0=float(t0) if t0 is not None else float("nan"),
    )
    with open(out_path, "w", encoding="utf-8") as fh:
        write_meta = write_geqdsk_declared_rcentr(
            eq, fh, rcentr_m=float(auth.rcentr_m), label=label
        )

    digest = sha256_file(out_path)
    manifest = {
        "ok": True,
        "adr": "ADR-001",
        "format": "geqdsk",
        "path": str(Path(auth.output_relpath).as_posix()),
        "sha256": digest,
        "bytes": int(out_path.stat().st_size),
        "label": label,
        "shot": shot,
        "t0": t0,
        "rcentr_m": float(auth.rcentr_m),
        "rcentr_source": auth.rcentr_source,
        "cocos_declared": auth.cocos_declared,
        "cocos_note": auth.cocos_note,
        "profile_provenance": auth.profile_provenance,
        "profile_note": auth.profile_note,
        "writer": auth.writer,
        "write_meta": write_meta,
        "authority_version": auth.authority_version,
        "note": "Geometry export only — TORAX was not executed.",
    }
    man_path = out_path.parent / "export_manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["export_manifest"] = str(man_path.relative_to(run_dir)).replace("\\", "/")
    return manifest
