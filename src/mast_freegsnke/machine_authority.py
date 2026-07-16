from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

from .util import sha256_file, ensure_dir, write_json


REQUIRED_FILES = ("authority_manifest.json", "probe_geometry.json", "coil_geometry.json", "diagnostic_registry.json")


@dataclass(frozen=True)
class MachineAuthority:
    root: Path
    manifest: Dict[str, Any]
    probe_geometry: Dict[str, Any]
    coil_geometry: Dict[str, Any]
    diagnostic_registry: Dict[str, Any]


def _load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text())


def load_machine_authority(root: Path) -> MachineAuthority:
    root = Path(root)
    missing = [f for f in REQUIRED_FILES if not (root / f).exists()]
    if missing:
        raise FileNotFoundError(f"Machine authority missing required files: {', '.join(missing)} in {root}")
    manifest = _load_json(root / "authority_manifest.json")
    probe = _load_json(root / "probe_geometry.json")
    coil = _load_json(root / "coil_geometry.json")
    reg = _load_json(root / "diagnostic_registry.json")
    return MachineAuthority(root=root, manifest=manifest, probe_geometry=probe, coil_geometry=coil, diagnostic_registry=reg)


def _looks_like_template(text: str) -> bool:
    t = (text or "").strip().lower()
    return (
        "change_me" in t
        or t == "template"
        or t.endswith("-template")
        or "0.0-template" in t
        or t.startswith("template")
    )


def validate_machine_authority(ma: MachineAuthority) -> Dict[str, Any]:
    errors: List[str] = []

    def _req(d: Dict[str, Any], k: str, ctx: str) -> None:
        if k not in d:
            errors.append(f"missing:{ctx}:{k}")

    # Manifest
    _req(ma.manifest, "schema_version", "authority_manifest")
    _req(ma.manifest, "authority_name", "authority_manifest")
    _req(ma.manifest, "authority_version", "authority_manifest")
    _req(ma.manifest, "provenance", "authority_manifest")

    # Fail-closed: reject shipped templates / CHANGE_ME provenance (do not invent metrology).
    ver = str(ma.manifest.get("authority_version", ""))
    if _looks_like_template(ver):
        errors.append(f"template_authority_version:{ver}")
    prov = ma.manifest.get("provenance") or {}
    if isinstance(prov, dict):
        for k, v in prov.items():
            if _looks_like_template(str(v)):
                errors.append(f"template_provenance:{k}={v}")
    notes = str(ma.probe_geometry.get("notes", "") or "")
    if _looks_like_template(notes) or "template" in notes.lower():
        errors.append("template_probe_geometry_notes")

    # Probe geometry minimal checks (do not invent metrology; just structural)
    _req(ma.probe_geometry, "schema_version", "probe_geometry")
    _req(ma.probe_geometry, "flux_loops", "probe_geometry")
    _req(ma.probe_geometry, "pickup_coils", "probe_geometry")

    # Coil geometry checks
    _req(ma.coil_geometry, "schema_version", "coil_geometry")
    _req(ma.coil_geometry, "coils", "coil_geometry")

    # Registry checks
    _req(ma.diagnostic_registry, "schema_version", "diagnostic_registry")
    _req(ma.diagnostic_registry, "diagnostics", "diagnostic_registry")

    ok = len(errors) == 0
    return {"ok": ok, "errors": errors, "root": str(ma.root)}


def snapshot_machine_authority(ma: MachineAuthority, run_dir: Path) -> Dict[str, Any]:
    """Copy and hash machine authority into run_dir/machine_authority_snapshot.

    Returns a snapshot report with file hashes.
    """
    snap_dir = ensure_dir(Path(run_dir) / "machine_authority_snapshot")
    out: Dict[str, Any] = {
        "authority_name": ma.manifest.get("authority_name"),
        "authority_version": ma.manifest.get("authority_version"),
        "source_root": str(ma.root),
        "files": {},
    }

    for fn in REQUIRED_FILES:
        src = ma.root / fn
        dst = snap_dir / fn
        dst.write_bytes(src.read_bytes())
        out["files"][fn] = {
            "sha256": sha256_file(dst),
            "bytes": dst.stat().st_size,
        }

    write_json(snap_dir / "snapshot_report.json", out)
    return out


def machine_authority_from_dir(root: Path) -> Tuple[Optional[MachineAuthority], Dict[str, Any]]:
    """Best-effort load + validate for pipeline.

    Returns (ma_or_none, report_dict).
    """
    try:
        ma = load_machine_authority(root)
        rep = validate_machine_authority(ma)
        if not rep.get("ok", False):
            return None, rep
        return ma, rep
    except Exception as e:
        return None, {"ok": False, "errors": [f"{type(e).__name__}: {e}"], "root": str(root)}
