"""Reviewer-grade certify sequence for a completed SHOT/<N> run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from .reviewer_pack import build_reviewer_pack
from .replay.replayer import replay_run


def _load_manifest(run_dir: Path) -> Dict[str, Any]:
    p = Path(run_dir) / "manifest.json"
    if not p.exists():
        return {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def certify_run_dir(
    run_dir: Path,
    *,
    skip_replay: bool = False,
    skip_reviewer_pack: bool = False,
) -> Dict[str, Any]:
    """Run reviewer-pack + replay and write CERTIFY_REPORT.json.

    Returns a report with ``ok`` / ``tier`` (GREEN|YELLOW|RED). Does not invent metrics.
    """
    run_dir = Path(run_dir)
    report: Dict[str, Any] = {
        "run_dir": str(run_dir),
        "ok": False,
        "tier": "RED",
        "checks": {},
        "blocking": [],
        "warnings": [],
    }
    if not run_dir.is_dir():
        report["blocking"].append("run_dir_missing")
        _write(run_dir if run_dir.parent.exists() else Path.cwd(), report)
        return report

    man = _load_manifest(run_dir)
    report["checks"]["manifest_present"] = bool(man)
    status = str(man.get("status") or "")
    report["checks"]["manifest_status"] = status
    blocking = list(man.get("blocking_errors") or [])
    report["checks"]["manifest_blocking_errors"] = blocking
    if status.lower() not in {"success", "ok", "completed"}:
        report["blocking"].append(f"manifest_status={status!r}")
    if blocking:
        report["blocking"].append("manifest_has_blocking_errors")

    prov = run_dir / "provenance"
    report["checks"]["provenance_dir"] = prov.is_dir()
    if not prov.is_dir():
        report["warnings"].append("provenance_dir_missing")

    report["checks"]["machine_authority_report"] = (
        run_dir / "machine_authority_report.json"
    ).exists()

    if not skip_reviewer_pack:
        try:
            pack = build_reviewer_pack(run_dir=run_dir)
            report["checks"]["reviewer_pack"] = {
                "ok": True,
                "out_dir": pack.get("out_dir"),
                "copied": pack.get("copied"),
                "missing": pack.get("missing"),
            }
            missing = pack.get("missing") or []
            if missing:
                report["warnings"].append(f"reviewer_pack_missing_items:{len(missing)}")
        except Exception as e:
            report["checks"]["reviewer_pack"] = {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
            }
            report["warnings"].append("reviewer_pack_failed")

    if not skip_replay:
        try:
            rep = replay_run(run_dir, mode="strict")
            report["checks"]["replay"] = {
                "ok": bool(getattr(rep, "ok", False)),
                "n_missing": getattr(rep, "n_missing", None),
                "n_mismatch": getattr(rep, "n_mismatch", None),
                "env_match": getattr(rep, "env_match", None),
            }
            if not getattr(rep, "ok", False):
                report["blocking"].append("replay_failed")
        except Exception as e:
            report["checks"]["replay"] = {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
            }
            report["warnings"].append("replay_unavailable_or_failed")

    for cand in [
        run_dir / "FREEGSNKE_MACHINE_PROVENANCE.json",
        run_dir / "machine_authority" / "FREEGSNKE_MACHINE_PROVENANCE.json",
    ]:
        if cand.exists():
            try:
                prov_obj = json.loads(cand.read_text(encoding="utf-8"))
                report["checks"]["honest_limits"] = prov_obj.get("honest_limits")
            except Exception:
                pass
            break

    # Science gates (v11.7.0): mixed reconstruct / missing Ip residual → YELLOW
    science = None
    sa_path = run_dir / "01_summary" / "science_audit.json"
    if sa_path.exists():
        try:
            science = json.loads(sa_path.read_text(encoding="utf-8"))
        except Exception:
            science = None
    if not isinstance(science, dict) and man:
        science = man.get("science_audit") if isinstance(man.get("science_audit"), dict) else None

    if isinstance(science, dict):
        rq = science.get("reconstruction_quality") or {}
        evo = science.get("evolutive_ip") or {}
        passives = science.get("passive_resistivity") or {}
        report["checks"]["science_audit"] = {
            "reconstruction_hint": rq.get("science_tier_hint"),
            "evolutive_ip_ok": evo.get("ok"),
            "passive_status": passives.get("status"),
        }
        hint = rq.get("science_tier_hint")
        if hint in {"yellow_mixed_or_partial", "yellow_forward_gs_only"}:
            report["warnings"].append(f"reconstruction_quality:{hint}")
        elif hint == "red_no_solved_times":
            report["blocking"].append("reconstruction_quality_red_no_solved_times")
        if (run_dir / "evolutive" / "history.csv").exists() and not evo.get("ok"):
            report["warnings"].append("evolutive_ip_residual_unavailable")
        if passives.get("status") in {"awaiting_authority", "unknown"}:
            report["warnings"].append("passive_resistivity_awaiting_authority")
    elif (run_dir / "synthetic" / "synthetic_times.json").exists():
        report["warnings"].append("science_audit_missing")

    if report["blocking"]:
        report["tier"] = "RED"
        report["ok"] = False
    elif report["warnings"]:
        report["tier"] = "YELLOW"
        report["ok"] = True
    else:
        report["tier"] = "GREEN"
        report["ok"] = True

    _write(run_dir, report)
    return report


def _write(run_dir: Path, report: Dict[str, Any]) -> None:
    try:
        Path(run_dir).mkdir(parents=True, exist_ok=True)
        (Path(run_dir) / "CERTIFY_REPORT.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass


def certify_from_cli_args(
    *,
    run: Optional[str] = None,
    shot: Optional[int] = None,
    runs_dir: str = "SHOT",
    skip_replay: bool = False,
    skip_reviewer_pack: bool = False,
) -> Dict[str, Any]:
    if run:
        run_dir = Path(run)
    elif shot is not None:
        run_dir = Path(runs_dir) / str(int(shot))
    else:
        raise ValueError("certify requires --run or --shot")
    return certify_run_dir(
        run_dir, skip_replay=skip_replay, skip_reviewer_pack=skip_reviewer_pack
    )
