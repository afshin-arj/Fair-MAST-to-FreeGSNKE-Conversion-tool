"""Rebuild classic MAST FreeGSNKE pickles when FAIR-MAST wall/pf_active fingerprints change."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .classic_mast_machine import ClassicMastMachineError, write_classic_mast_machine
from .honest_limits import machine_needs_rebuild, shot_cache_machine_fingerprints


def maybe_rebuild_classic_machine(
    shot_cache: Path,
    machine_dir: Path,
    *,
    shot: Optional[int] = None,
    force: bool = False,
    archive_mastu: bool = False,
) -> Dict[str, Any]:
    """Rebuild ``machine_dir`` from ``shot_cache`` when fingerprints disagree or ``force``.

    Returns a report with ``rebuilt`` bool. Never invents geometry: uses Level-2 only.
    """
    shot_cache = Path(shot_cache)
    machine_dir = Path(machine_dir)
    needs, check = machine_needs_rebuild(shot_cache, machine_dir)
    report: Dict[str, Any] = {
        "ok": True,
        "rebuilt": False,
        "force": bool(force),
        "needs_rebuild": bool(needs),
        "check": check,
        "fingerprints": shot_cache_machine_fingerprints(shot_cache),
    }
    if not force and not needs:
        return report

    try:
        build = write_classic_mast_machine(
            shot_cache,
            machine_dir,
            shot=shot,
            archive_mastu=archive_mastu,
            validate_tokamak=False,
        )
    except ClassicMastMachineError as e:
        report["ok"] = False
        report["error"] = str(e)
        return report

    # Attach fingerprints into provenance (write_classic already wrote provenance).
    _inject_fingerprints(machine_dir, report["fingerprints"])
    report["rebuilt"] = True
    report["build"] = {
        "n_limiter_points": build.get("n_limiter_points"),
        "circuits": build.get("circuits"),
        "limiter_source": (build.get("limiter_meta") or {}).get("source"),
    }
    # Re-check should be clean.
    needs2, check2 = machine_needs_rebuild(shot_cache, machine_dir)
    report["post_check"] = check2
    report["ok"] = not needs2 and bool(build.get("ok"))
    return report


def _inject_fingerprints(machine_dir: Path, fingerprints: Dict[str, Any]) -> None:
    import json

    prov_path = Path(machine_dir) / "FREEGSNKE_MACHINE_PROVENANCE.json"
    if not prov_path.exists():
        return
    obj = json.loads(prov_path.read_text(encoding="utf-8"))
    obj["source_fingerprints"] = {
        "wall": fingerprints.get("wall"),
        "pf_active": fingerprints.get("pf_active"),
    }
    prov_path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
