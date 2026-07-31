"""FAIR-MAST → GSFit database-reader adapter (ADR-006 scaffold).

Populates the surface needed to initialise a GSFit run from Fair-MAST extracts +
``machine_authority`` once calibration and Green’s are cited. While authorities
await, :func:`mast_freegsnke.gsfit_stage.run_gsfit_stage` never calls this module.

This adapter does **not** invent Green’s or V→T scales. Green’s load only from the
cited ``gsfit_greens`` pack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .gsfit_stage import GsfitAuthority


def describe_fairmast_mapping() -> Dict[str, Any]:
    """Document channel families for experts (honest, no invented numbers)."""
    return {
        "coils": {
            "source": "pf_active + coil_map authority → FreeGSNKE active vector names",
            "units": "A",
        },
        "flux_loops": {
            "source": "magnetics FL_* + probe_geometry.json",
            "units": "Wb (COCOS 13)",
            "needs": "cited inclusion list in gsfit_settings",
        },
        "bp_probes": {
            "source": "mirnov / poloidal probes after diagnostic_calibration V→T",
            "units": "T",
            "needs": "non-empty diagnostic_calibration.channels",
        },
        "rogowski_coils": {
            "source": "Ip / Rogowski from magnetics or summary",
            "units": "A",
            "needs": "cited channel names in settings",
        },
        "greens": {
            "source": "machine_authority/gsfit_greens (cited provenance only)",
            "never": "silent FreeGSNKE or ST40 matrix copy",
        },
        "passives": {
            "source": "configs/passive_resistivity.json (ADR-005)",
            "note": "empty DoF while awaiting_authority",
        },
    }


def load_greens_manifest(greens_dir: Path) -> Dict[str, Any]:
    greens_dir = Path(greens_dir)
    prov_path = greens_dir / "provenance.json"
    if not prov_path.is_file():
        raise FileNotFoundError(f"greens provenance missing: {prov_path}")
    obj = json.loads(prov_path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("greens provenance must be object")
    return obj


def build_init_context(
    *,
    shot: int,
    run_dir: Path,
    auth: "GsfitAuthority",
    repo_root: Path,
) -> Dict[str, Any]:
    """Assemble paths and mapping metadata for a future Gsfit() call."""
    repo_root = Path(repo_root)
    run_dir = Path(run_dir)

    def _p(rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (repo_root / p).resolve()

    greens_dir = _p(auth.greens_authority_path)
    settings_dir = _p(auth.settings_pack_path)
    return {
        "shot": int(shot),
        "run_dir": str(run_dir),
        "settings_pack": str(settings_dir),
        "greens_dir": str(greens_dir),
        "diagnostic_calibration": str(_p(auth.diagnostic_calibration_path)),
        "probe_geometry": str(_p(auth.probe_geometry_path)),
        "passive_resistivity": str(_p(auth.passive_resistivity_path)),
        "mapping": describe_fairmast_mapping(),
        "psi_convention_gsfit": auth.psi_convention_gsfit,
        "cocos": auth.cocos,
        "time_policy": auth.time_policy,
        "n_times": auth.n_times,
        "feed_targets_from_gsfit": auth.feed_targets_from_gsfit,
    }


def run_gsfit_fairmast_solve(
    *,
    shot: int,
    run_dir: Path,
    auth: "GsfitAuthority",
    repo_root: Path,
    out_dir: Path,
) -> Dict[str, Any]:
    """Attempt a live GSFit solve once authorities and package are ready.

    Returns a result dict. If the upstream GSFit public API cannot be driven from
    FAIR-MAST yet (reader not fully wired to Rust objects), returns
    ``ok=false`` with an honest fix_hint — never invents equilibria.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = build_init_context(
        shot=shot, run_dir=run_dir, auth=auth, repo_root=repo_root
    )
    ctx_path = out_dir / "init_context.json"
    ctx_path.write_text(json.dumps(ctx, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files: List[str] = [str(ctx_path)]

    try:
        import gsfit  # noqa: F401
    except Exception as e:
        return {
            "ok": False,
            "status": "blocked_import",
            "errors": [f"gsfit import failed: {type(e).__name__}: {e}"],
            "fix_hint": "pip install gsfit  (requirements-gsfit.txt)",
            "files_written": files,
        }

    try:
        load_greens_manifest(Path(ctx["greens_dir"]))
    except Exception as e:
        return {
            "ok": False,
            "status": "failed",
            "errors": [f"greens load: {type(e).__name__}: {e}"],
            "fix_hint": "Cite Green’s under machine_authority/gsfit_greens/",
            "files_written": files,
        }

    # Honest scaffold: FAIR-MAST database_reader is not yet contributed upstream.
    # When authorities are ready, experts still need the reader wired to GSFit's
    # Python init surface. Do not pretend a solve succeeded.
    adapter_note = out_dir / "ADAPTER.md"
    adapter_note.write_text(
        "\n".join(
            [
                "# GSFit FAIR-MAST adapter",
                "",
                "Authorities and `gsfit` import are ready, but the in-repo FAIR-MAST",
                "`database_reader` still needs device-specific wiring to GSFit's Rust",
                "objects (coils, sensors, Green’s binding by name).",
                "",
                "See `init_context.json` for paths and mapping notes.",
                "Upstream pattern: `python/gsfit/database_readers/` + settings JSON.",
                "Contribute a `fairmast` reader or complete this adapter before claiming",
                "a live EFIT-like solve.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    files.append(str(adapter_note))
    return {
        "ok": False,
        "status": "adapter_incomplete",
        "errors": [
            "FAIR-MAST GSFit database_reader adapter not yet able to drive a live solve"
        ],
        "fix_hint": (
            "Complete src/mast_freegsnke/gsfit_fairmast_reader.py against GSFit's "
            "database_readers interface once calib/Green’s/settings are cited; "
            "or contribute a fairmast reader upstream."
        ),
        "files_written": files,
        "init_context": ctx,
    }
