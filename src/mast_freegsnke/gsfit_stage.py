"""ADR-006: GSFit live reconstruction peer — authority-gated scaffold.

While ``gsfit_authority.status=awaiting_authority`` (or prerequisites unfinished), the
stage soft-skips and writes ``08_gsfit/GSFIT.md`` + ``GSFIT.json`` with a checklist.
Never invents calibration, Green’s, or sensor weights. Does not replace ADR-002 EFIT++
archive compare or FreeGSNKE.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class GsfitAuthorityError(ValueError):
    pass


_READY_STATUSES = frozenset({"ready", "populated", "cited", "ok"})
_AWAITING_STATUSES = frozenset(
    {"awaiting_authority", "awaiting", "empty", "scaffold", ""}
)


@dataclass(frozen=True)
class GsfitAuthority:
    authority_name: str = "gsfit"
    authority_version: str = "1.0"
    status: str = "awaiting_authority"
    label: str = "GSFit live reconstruction peer (not EFIT++ / efit-ai / Py-EFIT)"
    source: str = "https://github.com/tokamak-energy/gsfit"
    citation: str = ""
    require: bool = False
    feed_targets_from_gsfit: bool = False
    optional_dependency: str = "gsfit"
    psi_convention_gsfit: str = "Wb"
    psi_convention_scorecard: str = "Wb_per_2pi"
    psi_to_scorecard_factor: float = 2.0 * math.pi
    cocos: int = 13
    output_relpath: str = "08_gsfit"
    time_policy: str = "window_linspace"
    n_times: int = 5
    settings_pack_path: str = "machine_authority/gsfit_settings"
    greens_authority_path: str = "machine_authority/gsfit_greens"
    diagnostic_calibration_path: str = "configs/diagnostic_calibration.json"
    probe_geometry_path: str = "machine_authority/probe_geometry.json"
    passive_resistivity_path: str = "configs/passive_resistivity.json"
    awaiting: Tuple[str, ...] = ()
    notes: str = ""
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def status_awaiting(self) -> bool:
        return self.status.strip().lower() in _AWAITING_STATUSES

    @property
    def status_ready_declared(self) -> bool:
        return self.status.strip().lower() in _READY_STATUSES

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in asdict(self).items() if k != "raw"}
        d["awaiting"] = list(self.awaiting)
        return d


def load_gsfit_authority(path: Path) -> GsfitAuthority:
    path = Path(path)
    if not path.exists():
        raise GsfitAuthorityError(f"gsfit_authority not found: {path}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise GsfitAuthorityError(f"invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise GsfitAuthorityError("root must be object")
    awaiting = obj.get("awaiting") or []
    if not isinstance(awaiting, list):
        raise GsfitAuthorityError("awaiting must be a list of strings")
    factor = obj.get("psi_to_scorecard_factor", 2.0 * math.pi)
    try:
        factor_f = float(factor)
    except (TypeError, ValueError) as e:
        raise GsfitAuthorityError(f"psi_to_scorecard_factor must be float: {e}") from e
    n_times = int(obj.get("n_times", 5) or 5)
    if n_times < 1:
        raise GsfitAuthorityError("n_times must be >= 1")
    return GsfitAuthority(
        authority_name=str(obj.get("authority_name", "gsfit")),
        authority_version=str(obj.get("authority_version", "1.0")),
        status=str(obj.get("status", "awaiting_authority")),
        label=str(
            obj.get(
                "label",
                "GSFit live reconstruction peer (not EFIT++ / efit-ai / Py-EFIT)",
            )
        ),
        source=str(obj.get("source", "https://github.com/tokamak-energy/gsfit")),
        citation=str(obj.get("citation", "")),
        require=bool(obj.get("require", False)),
        feed_targets_from_gsfit=bool(obj.get("feed_targets_from_gsfit", False)),
        optional_dependency=str(obj.get("optional_dependency", "gsfit")),
        psi_convention_gsfit=str(obj.get("psi_convention_gsfit", "Wb")),
        psi_convention_scorecard=str(obj.get("psi_convention_scorecard", "Wb_per_2pi")),
        psi_to_scorecard_factor=factor_f,
        cocos=int(obj.get("cocos", 13) or 13),
        output_relpath=str(obj.get("output_relpath", "08_gsfit")),
        time_policy=str(obj.get("time_policy", "window_linspace")),
        n_times=n_times,
        settings_pack_path=str(
            obj.get("settings_pack_path", "machine_authority/gsfit_settings")
        ),
        greens_authority_path=str(
            obj.get("greens_authority_path", "machine_authority/gsfit_greens")
        ),
        diagnostic_calibration_path=str(
            obj.get("diagnostic_calibration_path", "configs/diagnostic_calibration.json")
        ),
        probe_geometry_path=str(
            obj.get("probe_geometry_path", "machine_authority/probe_geometry.json")
        ),
        passive_resistivity_path=str(
            obj.get("passive_resistivity_path", "configs/passive_resistivity.json")
        ),
        awaiting=tuple(str(x) for x in awaiting),
        notes=str(obj.get("notes", "")),
        raw=obj,
    )


def write_gsfit_authority(inputs_dir: Path, auth: GsfitAuthority) -> Path:
    out_dir = Path(inputs_dir) / "gsfit_authority"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "gsfit_authority.json"
    payload = dict(auth.raw) if auth.raw else auth.to_dict()
    # Keep snapshot honest with loaded status fields
    payload.update(auth.to_dict())
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _resolve_repo_path(rel_or_abs: str, repo_root: Path) -> Path:
    p = Path(rel_or_abs)
    if p.is_absolute():
        return p
    return (repo_root / p).resolve()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def check_diagnostic_calibration(path: Path) -> Dict[str, Any]:
    obj = _load_json(path)
    if obj is None:
        return {
            "ok": False,
            "id": "diagnostic_calibration",
            "status": "missing",
            "detail": f"file missing: {path}",
        }
    status = str(obj.get("status", "awaiting_authority")).lower()
    channels = obj.get("channels") or {}
    n = len(channels) if isinstance(channels, dict) else 0
    awaiting = status in _AWAITING_STATUSES or n == 0
    return {
        "ok": not awaiting,
        "id": "diagnostic_calibration",
        "status": "awaiting_authority" if awaiting else status,
        "detail": f"channels={n}; status={status}",
        "n_channels": n,
    }


def check_greens_authority(path: Path) -> Dict[str, Any]:
    path = Path(path)
    prov = _load_json(path / "provenance.json")
    if prov is None:
        return {
            "ok": False,
            "id": "greens_authority",
            "status": "awaiting_authority",
            "detail": f"provenance.json missing under {path}",
        }
    status = str(prov.get("status", "awaiting_authority")).lower()
    files = prov.get("files") or []
    source = str(prov.get("source") or "").strip()
    cited = (
        status in _READY_STATUSES
        and isinstance(files, list)
        and len(files) > 0
        and bool(source)
    )
    return {
        "ok": cited,
        "id": "greens_authority",
        "status": "cited" if cited else "awaiting_authority",
        "detail": f"status={status}; files={len(files) if isinstance(files, list) else 0}; source={'yes' if source else 'no'}",
        "n_files": len(files) if isinstance(files, list) else 0,
    }


def check_settings_pack(path: Path) -> Dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {
            "ok": False,
            "id": "settings_pack",
            "status": "missing",
            "detail": f"settings pack missing: {path}",
        }
    # Prefer README_authority.json or any *.json with status
    candidates = sorted(path.glob("*.json"))
    if not candidates:
        return {
            "ok": False,
            "id": "settings_pack",
            "status": "awaiting_authority",
            "detail": "no JSON settings files",
        }
    # Use first JSON that declares status, else first file
    chosen = None
    for c in candidates:
        obj = _load_json(c)
        if obj and "status" in obj:
            chosen = (c, obj)
            break
    if chosen is None:
        chosen = (candidates[0], _load_json(candidates[0]) or {})
    cpath, obj = chosen
    status = str(obj.get("status", "awaiting_authority")).lower()
    awaiting = status in _AWAITING_STATUSES
    sensors = obj.get("sensors") if isinstance(obj.get("sensors"), dict) else {}
    n_include = 0
    for fam in sensors.values():
        if isinstance(fam, dict):
            inc = fam.get("include") or []
            if isinstance(inc, list):
                n_include += len(inc)
    ready = (not awaiting) and n_include > 0
    return {
        "ok": ready,
        "id": "settings_pack",
        "status": "ready" if ready else "awaiting_authority",
        "detail": f"{cpath.name}: status={status}; sensor_includes={n_include}",
        "n_sensor_includes": n_include,
    }


def check_probe_geometry(path: Path) -> Dict[str, Any]:
    obj = _load_json(path)
    if obj is None:
        return {
            "ok": False,
            "id": "probe_geometry",
            "status": "missing",
            "detail": f"missing: {path}",
        }
    fl = obj.get("flux_loops") or []
    n_fl = len(fl) if isinstance(fl, list) else 0
    # Geometry can exist while calib awaits — geometry presence is a hard prereq for ready
    ok = n_fl > 0
    return {
        "ok": ok,
        "id": "probe_geometry",
        "status": "ok" if ok else "empty",
        "detail": f"flux_loops={n_fl}",
        "n_flux_loops": n_fl,
    }


def check_gsfit_import() -> Dict[str, Any]:
    try:
        import gsfit  # noqa: F401

        ver = getattr(gsfit, "__version__", None)
        return {
            "ok": True,
            "id": "gsfit_import",
            "status": "installed",
            "detail": f"gsfit import ok{f' ({ver})' if ver else ''}",
            "version": ver,
        }
    except Exception as e:
        return {
            "ok": False,
            "id": "gsfit_import",
            "status": "not_installed",
            "detail": f"{type(e).__name__}: {e}",
        }


@dataclass(frozen=True)
class GsfitReadiness:
    ready: bool
    status: str
    checks: Tuple[Dict[str, Any], ...]
    blocking: Tuple[str, ...]
    checklist: Tuple[str, ...]
    gsfit_installed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ready": self.ready,
            "status": self.status,
            "checks": list(self.checks),
            "blocking": list(self.blocking),
            "checklist": list(self.checklist),
            "gsfit_installed": self.gsfit_installed,
        }


def gsfit_readiness(
    auth: GsfitAuthority,
    *,
    repo_root: Path,
    check_import: bool = True,
) -> GsfitReadiness:
    """Evaluate whether a live GSFit solve may run (never invents metrology)."""
    repo_root = Path(repo_root)
    checks: List[Dict[str, Any]] = []
    blocking: List[str] = []
    checklist: List[str] = list(auth.awaiting)

    if auth.status_awaiting:
        blocking.append("gsfit_authority.status=awaiting_authority")
        if not checklist:
            checklist = [
                "Populate diagnostic_calibration channels",
                "Cite Green’s under machine_authority/gsfit_greens/",
                "Fill machine_authority/gsfit_settings/",
                "pip install gsfit",
                "Set gsfit_authority.status to ready",
            ]

    cal = check_diagnostic_calibration(
        _resolve_repo_path(auth.diagnostic_calibration_path, repo_root)
    )
    checks.append(cal)
    if not cal["ok"]:
        blocking.append("diagnostic_calibration_awaiting")

    greens = check_greens_authority(
        _resolve_repo_path(auth.greens_authority_path, repo_root)
    )
    checks.append(greens)
    if not greens["ok"]:
        blocking.append("greens_authority_awaiting")

    settings = check_settings_pack(
        _resolve_repo_path(auth.settings_pack_path, repo_root)
    )
    checks.append(settings)
    if not settings["ok"]:
        blocking.append("settings_pack_awaiting")

    geom = check_probe_geometry(_resolve_repo_path(auth.probe_geometry_path, repo_root))
    checks.append(geom)
    if not geom["ok"]:
        blocking.append("probe_geometry_missing")

    installed = False
    if check_import:
        imp = check_gsfit_import()
        checks.append(imp)
        installed = bool(imp["ok"])
    else:
        checks.append(
            {
                "ok": False,
                "id": "gsfit_import",
                "status": "skipped",
                "detail": "check_import=false",
            }
        )

    # Declared ready + all prereqs except import (import checked at run time for fail-closed)
    prereqs_ok = (
        auth.status_ready_declared
        and cal["ok"]
        and greens["ok"]
        and settings["ok"]
        and geom["ok"]
    )
    if prereqs_ok and check_import and not installed:
        blocking.append("gsfit_not_installed")

    ready = prereqs_ok and (installed if check_import else True) and not auth.status_awaiting
    status = "ready" if ready else ("awaiting_authority" if not prereqs_ok else "blocked_import")
    if auth.status_awaiting:
        status = "awaiting_authority"

    return GsfitReadiness(
        ready=ready,
        status=status,
        checks=tuple(checks),
        blocking=tuple(dict.fromkeys(blocking)),
        checklist=tuple(checklist),
        gsfit_installed=installed,
    )


@dataclass
class GsfitStageReport:
    ok: bool = False
    status: str = "awaiting_authority"
    label: str = ""
    output_dir: str = ""
    authority_version: str = "1.0"
    require: bool = False
    feed_targets_from_gsfit: bool = False
    psi_convention_gsfit: str = "Wb"
    psi_convention_scorecard: str = "Wb_per_2pi"
    psi_to_scorecard_factor: float = 2.0 * math.pi
    readiness: Optional[Dict[str, Any]] = None
    files_written: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    fix_hint: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _write_report_files(out_dir: Path, report: GsfitStageReport) -> List[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    jpath = out_dir / "GSFIT.json"
    jpath.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(str(jpath))

    lines = [
        "# GSFit live peer (ADR-006)",
        "",
        f"**Status:** `{report.status}`",
        f"**ok:** `{report.ok}`",
        f"**Label:** {report.label}",
        "",
        "This is a **live GSFit** reconstruction peer — **not** EFIT++ / efit-ai / Py-EFIT.",
        "FAIR-MAST EFIT++ archive compare remains under `04_efit_compare/` (ADR-002).",
        "FreeGSNKE remains the shot-only happy-path solver.",
        "",
        f"ψ convention (GSFit): `{report.psi_convention_gsfit}` (COCOS 13).",
        f"Scorecard convention: `{report.psi_convention_scorecard}` "
        f"(× `{report.psi_to_scorecard_factor}` when converting).",
        "",
    ]
    if report.readiness:
        lines.append("## Readiness checklist")
        lines.append("")
        for item in report.readiness.get("checklist") or []:
            lines.append(f"- [ ] {item}")
        lines.append("")
        lines.append("## Checks")
        lines.append("")
        for ch in report.readiness.get("checks") or []:
            if not isinstance(ch, dict):
                continue
            mark = "OK" if ch.get("ok") else "BLOCK"
            lines.append(
                f"- **{ch.get('id')}** [{mark}]: {ch.get('status')} — {ch.get('detail')}"
            )
        lines.append("")
        if report.readiness.get("blocking"):
            lines.append("## Blocking")
            lines.append("")
            for b in report.readiness["blocking"]:
                lines.append(f"- `{b}`")
            lines.append("")
    if report.fix_hint:
        lines.extend(["## Fix hint", "", report.fix_hint, ""])
    if report.errors:
        lines.extend(["## Errors", ""])
        for e in report.errors:
            lines.append(f"- {e}")
        lines.append("")
    if report.notes:
        lines.extend(["## Notes", "", report.notes, ""])
    lines.extend(
        [
            "## Activation",
            "",
            "See `docs/gsfit_authority_checklist.md`.",
            "",
        ]
    )
    mpath = out_dir / "GSFIT.md"
    mpath.write_text("\n".join(lines), encoding="utf-8")
    written.append(str(mpath))
    report.files_written = written
    return written


def run_gsfit_stage(
    run_dir: Path,
    *,
    shot: int,
    auth: GsfitAuthority,
    repo_root: Path,
    solve_fn: Optional[Any] = None,
) -> GsfitStageReport:
    """Run or soft-skip the GSFit peer stage.

    ``solve_fn`` is an optional callable ``(ctx) -> dict`` for tests / future wiring.
    When readiness is true and ``solve_fn`` is None, attempts a real GSFit solve via
    :mod:`mast_freegsnke.gsfit_fairmast_reader` (may still soft-fail if adapter incomplete).
    """
    run_dir = Path(run_dir)
    repo_root = Path(repo_root)
    out_dir = run_dir / auth.output_relpath
    report = GsfitStageReport(
        ok=False,
        status="awaiting_authority",
        label=auth.label,
        output_dir=str(out_dir),
        authority_version=auth.authority_version,
        require=auth.require,
        feed_targets_from_gsfit=auth.feed_targets_from_gsfit,
        psi_convention_gsfit=auth.psi_convention_gsfit,
        psi_convention_scorecard=auth.psi_convention_scorecard,
        psi_to_scorecard_factor=auth.psi_to_scorecard_factor,
        notes=auth.notes,
    )

    readiness = gsfit_readiness(auth, repo_root=repo_root, check_import=True)
    report.readiness = readiness.to_dict()

    if not readiness.ready:
        # Soft-skip unless require=true (then caller treats ok=False as blocking)
        report.status = readiness.status
        report.ok = False
        if auth.status_ready_declared and not readiness.gsfit_installed:
            report.errors.append(
                "gsfit_authority status is ready but package not importable"
            )
            report.fix_hint = (
                "pip install gsfit  (or: pip install -r requirements-gsfit.txt)"
            )
            report.status = "blocked_import"
        else:
            report.fix_hint = (
                "Populate diagnostic_calibration, gsfit_greens provenance, and "
                "gsfit_settings; then set gsfit_authority.status=ready. "
                "See docs/gsfit_authority_checklist.md"
            )
        _write_report_files(out_dir, report)
        return report

    # Ready path
    try:
        if solve_fn is not None:
            result = solve_fn(
                {
                    "shot": int(shot),
                    "run_dir": run_dir,
                    "auth": auth,
                    "repo_root": repo_root,
                    "out_dir": out_dir,
                }
            )
        else:
            from .gsfit_fairmast_reader import run_gsfit_fairmast_solve

            result = run_gsfit_fairmast_solve(
                shot=int(shot),
                run_dir=run_dir,
                auth=auth,
                repo_root=repo_root,
                out_dir=out_dir,
            )
        if not isinstance(result, dict):
            raise GsfitAuthorityError("solve returned non-dict")
        report.ok = bool(result.get("ok"))
        report.status = str(result.get("status", "ok" if report.ok else "failed"))
        report.errors = list(result.get("errors") or [])
        report.fix_hint = str(result.get("fix_hint") or "")
        extra_files = list(result.get("files_written") or [])
        _write_report_files(out_dir, report)
        report.files_written = list(dict.fromkeys(report.files_written + extra_files))
        # refresh JSON with merged files_written
        (out_dir / "GSFIT.json").write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report
    except Exception as e:
        report.ok = False
        report.status = "failed"
        report.errors.append(f"{type(e).__name__}: {e}")
        report.fix_hint = (
            "GSFit solve raised; check settings/Green’s/calib authorities and logs."
        )
        _write_report_files(out_dir, report)
        return report
