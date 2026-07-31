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
            "evolutive_ip_status": evo.get("status"),
            "evolutive_raxis_status": (science.get("evolutive_raxis_drift") or {}).get("status"),
            "passive_status": passives.get("status"),
        }
        hint = rq.get("science_tier_hint")
        if hint in {"yellow_mixed_or_partial", "yellow_forward_gs_only"}:
            report["warnings"].append(f"reconstruction_quality:{hint}")
        elif hint == "red_no_solved_times":
            report["blocking"].append("reconstruction_quality_red_no_solved_times")
        from .shot_layout import resolve_run_path

        evo_hist = resolve_run_path(
            run_dir,
            "evolutive/history.csv",
            "03_reconstruction/evolutive/history.csv",
        )
        if evo_hist is not None and evo_hist.exists() and not evo.get("ok"):
            report["warnings"].append("evolutive_ip_residual_unavailable")
        if evo.get("status") == "clamp_tautology":
            report["warnings"].append("evolutive_ip_clamp_tautology")
        rax = science.get("evolutive_raxis_drift") or {}
        if rax.get("status") == "early_stop_axis_drift":
            report["warnings"].append("evolutive_early_stop_axis_drift")
        if passives.get("status") in {"awaiting_authority", "unknown"}:
            report["warnings"].append("passive_resistivity_awaiting_authority")
    elif (run_dir / "synthetic" / "synthetic_times.json").exists():
        report["warnings"].append("science_audit_missing")

    # ADR-006: GSFit live peer awaiting or incomplete → YELLOW (not red unless require)
    gsfit_json = run_dir / "08_gsfit" / "GSFIT.json"
    if gsfit_json.is_file():
        try:
            gs = json.loads(gsfit_json.read_text(encoding="utf-8"))
        except Exception:
            gs = None
        if isinstance(gs, dict):
            report["checks"]["gsfit"] = {
                "ok": gs.get("ok"),
                "status": gs.get("status"),
                "require": gs.get("require"),
                "authority_version": gs.get("authority_version"),
            }
            st = str(gs.get("status") or "")
            if st in {"awaiting_authority", "blocked_import", "adapter_incomplete"} or not gs.get(
                "ok"
            ):
                if st == "awaiting_authority" or (
                    isinstance(gs.get("readiness"), dict)
                    and gs["readiness"].get("status") == "awaiting_authority"
                ):
                    report["warnings"].append("gsfit_awaiting_authority")
                elif st in {"blocked_import", "adapter_incomplete"}:
                    report["warnings"].append(f"gsfit_{st}")
                elif gs.get("require") and not gs.get("ok"):
                    report["blocking"].append("gsfit_required_but_not_ok")
                elif not gs.get("ok") and st not in {"", "execute_gsfit=false"}:
                    report["warnings"].append(f"gsfit_not_ok:{st or 'failed'}")

    # Path B0/B2: GSPulse-method planner incomplete (no Picard; isoflux soft-skip) → YELLOW
    planner_json = run_dir / "07_planner" / "PLANNER.json"
    if planner_json.is_file():
        try:
            pl = json.loads(planner_json.read_text(encoding="utf-8"))
        except Exception:
            pl = None
        if isinstance(pl, dict):
            report["checks"]["planner"] = {
                "method": pl.get("method"),
                "method_version": pl.get("method_version"),
                "picard": pl.get("picard"),
                "isoflux_cost": pl.get("isoflux_cost"),
                "isoflux_mode": pl.get("isoflux_mode"),
                "status": pl.get("status"),
                "shape_targets_present": (pl.get("shape_targets_available") or {}).get(
                    "present"
                ),
                "circuit_dynamics_mutuals": pl.get("circuit_dynamics_mutuals"),
            }
            if pl.get("method") == "gspulse_python":
                auth_pl: Optional[Dict[str, Any]] = None
                auth_path = run_dir / "inputs" / "planner_authority" / "planner_authority.json"
                if auth_path.is_file():
                    try:
                        obj = json.loads(auth_path.read_text(encoding="utf-8"))
                        auth_pl = obj if isinstance(obj, dict) else None
                    except Exception:
                        auth_pl = None
                req_iso = bool((auth_pl or {}).get("require_isoflux") or pl.get("require_isoflux"))
                req_pic = bool((auth_pl or {}).get("require_picard") or pl.get("require_picard"))
                if pl.get("picard") is False and not req_pic:
                    report["warnings"].append(
                        "planner_gspulse_python_incomplete:picard_not_wired"
                    )
                elif pl.get("picard") is False and req_pic:
                    report["blocking"].append("planner_require_picard_unmet")
                if pl.get("isoflux_cost") is False and not req_iso:
                    report["warnings"].append(
                        "planner_gspulse_python_incomplete:isoflux_not_wired"
                    )
                elif pl.get("isoflux_cost") is False and req_iso:
                    report["blocking"].append("planner_require_isoflux_unmet")
                if pl.get("status") == "voltage_exceeds_measured_peak_margin":
                    report["warnings"].append(
                        "planner_voltage_exceeds_measured_peak_margin"
                    )
            report["checks"]["planner"]["picard_mode"] = pl.get("picard_mode")
            report["checks"]["planner"]["picard_status"] = pl.get("picard_status")
            if (pl.get("circuit_dynamics_mutuals") or "").startswith("neglected"):
                report["warnings"].append(
                    "planner_circuit_mutuals_neglected_diagonal_only"
                )
    elif (run_dir / "inputs" / "planner_authority" / "planner_authority.json").is_file():
        report["warnings"].append("planner_authority_present_but_PLANNER_json_missing")

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
