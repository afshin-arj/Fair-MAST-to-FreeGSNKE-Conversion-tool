"""Expert-facing SHOT/<N>/ index layer (00_README + 01_summary).

Operational paths (inputs/, synthetic/, metrics/, logs/, manifest.json, *.py)
remain at the run root for tooling stability. This module only adds the
human/expert overlay. v11.7.0: science-first SUMMARY (residuals, solve_mode,
evolutive Ip, ohmic drive uncertainty, phases); GIFs are annex.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


_KNOWN_LIMITATIONS = [
    "Structural machine is classic MAST built from FAIR-MAST Level-2 filaments (machine_authority/; see FREEGSNKE_MACHINE_PROVENANCE.json) — not FreeGSNKE MAST-U pickles.",
    "Limiter/wall = FAIR-MAST wall.zarr limiter_r/z (EFIT limiter geometry) — not surveyed CAD vessel; not a flux-loop computational proxy.",
    "No FreeGSNKE passives: Level-2 pf_passive has parallelogram geometry but no resistivity (do not invent resistivity). Populate configs/passive_resistivity.json only with cited ρ.",
    "FAIR-MAST Level-2 supplies measured voltages (p1/p2/p4/p5 in V) as primary evolutive drive; p2 is applied identically to P2_inner and P2_outer (declared same-V policy).",
    "P3 and P6: no usable measured PF voltage in public L1/L2 -> from_current_ohmic (I*R with FreeGSNKE coil_resist after load) — treat as declared uncertainty, not measured V.",
    "Active-coil resistivity is FreeGSNKE copper default 1.55e-8 (declared material constant; Level-2 does not publish coil resistivity).",
    "Profile alpha_m/alpha_n/fvac are held from the inverse IC; optional scale_paxis_with_ip is a declared Ip scaling law (default off) — never invented profile numbers.",
    "Evolutive default: ic_coil_currents=measured_pf + clamp_ip_to_measured (experimental I+V at t0); inverse_dump remains DEMO/shape-IC. Under clamp_ip, Ip residual is a tautology — prefer Raxis drift / early_stop. n_passive=0 → example05-class stability not expected (do not invent ρ).",
    "Contract residual metrics score only families with honest channel identity + units; uncalibrated mirnov/saddle/omaha stay audit-only until calibration authority is populated.",
    "FreeGSNKE Inverse stops on GS residual / relative ψ update only; constraint loss and DN X/O placement are scored by declared inverse_shape_acceptance (not a FreeGSNKE stop). GS ok ≠ automatic DN success.",
    "Static Forward: t0 uses Inverse dump currents (+ dump ψ IC by default); window uses solver.forward_window_currents (default measured_pf; optional inverse_dump_currents = shape DEMO only). Forward plots must use live Forward LCFS (never Inverse dump LCFS); measured-PF Forward is not Inverse DN success. Live LCFS polylines are clipped to the GS domain (R>Rmin, R>0) so separatrix rays through the solenoid are not drawn as plasma. n_converged counts tol-met GS only.",
    "Evolutive frames use live Evolutive LCFS only (never Inverse dump LCFS / Inverse null targets). early_stop=axis_drift is not an Ip-collapse claim (n_passive=0 soft-stop common). Evolutive stays soft-stop until cited ρ exists.",
    "profile_trajectory: richer α only from cited EFIT++ pprime (archive_profiles); scalar_bridge holds authority α — never invent α.",
    "Equilibrium GIFs are presentation annexes — not a substitute for residual metrics or Ip match. Curated plots draw structure-masked open-field contours (inside limiter; NaN through solenoid/PF coils) — Inverse/Forward/Evolutive.",
    "04_efit_compare uses FAIR-MAST Level-2 EFIT++ archive products — not a live efit-ai Fortran solve.",
]


def _safe_load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _exec_status(manifest: Dict[str, Any]) -> Dict[str, str]:
    fe = manifest.get("freegsnke_execution") or {}
    results = fe.get("results") or []
    by_label: Dict[str, str] = {}
    for r in results:
        script = str(r.get("script") or "")
        label = script.replace("_run.py", "").replace(".py", "") or "unknown"
        if r.get("ok"):
            by_label[label] = "ok"
        elif r.get("timed_out"):
            by_label[label] = "timeout"
        else:
            by_label[label] = "failed"
    if fe.get("skipped"):
        by_label["skipped"] = str(fe.get("skipped"))
    return by_label


def _metrics_rows(manifest: Dict[str, Any], run_dir: Path) -> List[str]:
    lines: List[str] = []
    m = manifest.get("reconstruction_metrics")
    if not isinstance(m, dict):
        from .shot_layout import resolve_run_path

        mp = resolve_run_path(
            run_dir,
            "03_reconstruction/metrics/reconstruction_metrics.json",
            "metrics/reconstruction_metrics.json",
        )
        m = _safe_load_json(mp) if mp is not None else {}
        m = m or {}
    if not m:
        lines.append("| (none) | — | — |")
        return lines
    lines.append(f"| n_scored | {m.get('n_scored', '—')} | contracts with finite residuals |")
    lines.append(f"| n_skipped_all_nan | {m.get('n_skipped_all_nan', '—')} | |")
    lines.append(f"| metrics_ok | {m.get('ok')} | |")
    per = m.get("per_contract") or []
    if isinstance(per, list):
        for row in per[:12]:
            if not isinstance(row, dict):
                continue
            name = row.get("name") or row.get("id") or "?"
            rms = row.get("rms")
            n = row.get("n")
            lines.append(f"| `{name}` RMS | {rms if rms is not None else '—'} | n={n} |")
        if len(per) > 12:
            lines.append(f"| … | ({len(per) - 12} more contracts) | see metrics/ |")
    return lines


def write_shot_expert_overlay(
    run_dir: Path,
    *,
    shot: int,
    manifest: Optional[Dict[str, Any]] = None,
    science_audit: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Write 00_README.txt and 01_summary/SUMMARY.md (+ timeline.txt).

    Returns relative paths written.
    """
    run_dir = Path(run_dir)
    if manifest is None:
        manifest = _safe_load_json(run_dir / "manifest.json") or {}

    summary_dir = run_dir / "01_summary"
    summary_dir.mkdir(parents=True, exist_ok=True)

    status = str(manifest.get("status", "unknown"))
    created = str(manifest.get("created_utc") or manifest.get("created") or "")
    tw = manifest.get("time_window") or {}
    t_start = tw.get("t_start")
    t_end = tw.get("t_end")
    exec_st = _exec_status(manifest)
    blocking = manifest.get("blocking_errors") or []
    stages = manifest.get("stage_log") or []
    from .equilibrium_presentation import presentation_gifs_under

    gifs = presentation_gifs_under(run_dir)

    if science_audit is None:
        science_audit = _safe_load_json(summary_dir / "science_audit.json") or manifest.get(
            "science_audit"
        )
    if not isinstance(science_audit, dict):
        science_audit = {}

    rq = science_audit.get("reconstruction_quality") or {}
    evo_ip = science_audit.get("evolutive_ip") or {}
    ohmic = science_audit.get("ohmic_drive") or {}
    phases = science_audit.get("phase_timeline") or {}
    passives = science_audit.get("passive_resistivity") or {}
    shape_gate = science_audit.get("inverse_shape_gate") or {}
    fwd_gate = science_audit.get("forward_gate") or {}
    advisories = science_audit.get("presentation_advisories") or {}
    if not advisories.get("items"):
        # Best-effort recompute if audit was written before v1.3
        try:
            from .science_audit import presentation_advisories as _pres_adv

            advisories = _pres_adv(run_dir)
        except Exception:
            advisories = {"available": False, "items": []}

    # Authority hashes (best-effort)
    auth_lines: List[str] = []
    for rel in [
        "06_authorities/contracts/voltage_map.sha256.json",
        "contracts/voltage_map.sha256.json",
        "06_authorities/contracts/coil_map.resolved.json",
        "contracts/coil_map.resolved.json",
        "06_authorities/provenance/hashes.json",
        "provenance/hashes.json",
        "06_authorities/machine_authority_snapshot/authority_manifest.json",
        "machine_authority_snapshot/authority_manifest.json",
    ]:
        p = run_dir / rel
        if p.exists():
            auth_lines.append(f"- `{rel}` present")
    vm_hash = _safe_load_json(run_dir / "06_authorities" / "contracts" / "voltage_map.sha256.json") or _safe_load_json(
        run_dir / "contracts" / "voltage_map.sha256.json"
    )
    if vm_hash and vm_hash.get("sha256"):
        auth_lines.append(f"- voltage_map sha256: `{vm_hash['sha256'][:16]}…`")

    phase_lines: List[str] = []
    if phases.get("available") and isinstance(phases.get("phases"), list):
        for ph in phases["phases"]:
            if isinstance(ph, dict):
                phase_lines.append(
                    f"| `{ph.get('phase')}` | {ph.get('t_start')} | {ph.get('t_end')} |"
                )
    if not phase_lines:
        phase_lines = ["| (none) | — | — |"]

    ohmic_list = ", ".join(ohmic.get("ohmic_circuits") or []) or "(none)"
    meas_v = ", ".join(ohmic.get("measured_voltage_circuits") or []) or "(none)"

    evo_ip_lines = [
        f"| status | {evo_ip.get('status', '—')} | clamp_tautology = not circuit validation |",
        f"| ok | {evo_ip.get('ok')} | |",
        f"| n | {evo_ip.get('n', '—')} | valid evolutive steps |",
        f"| steps | {evo_ip.get('n_steps_recorded', '—')}/{evo_ip.get('n_steps_requested', '—')} | recorded/requested |",
        f"| early_stop | {evo_ip.get('early_stop', '—')} | |",
        f"| ic_coil_currents | {evo_ip.get('ic_coil_currents', '—')} | |",
        f"| RMS [A] | {evo_ip.get('rms_A', '—')} | vs measured ip.csv |",
        f"| MAE [A] | {evo_ip.get('mae_A', '—')} | |",
        f"| max‖res‖ [A] | {evo_ip.get('max_abs_A', '—')} | |",
        f"| RMS rel | {evo_ip.get('rms_rel', '—')} | RMS / mean‖Ip_meas‖ |",
    ]
    if evo_ip.get("status") == "clamp_tautology":
        evo_ip_lines.append(
            "| note | Ip residual near zero is expected under clamp_ip — not voltage fidelity | |"
        )
    if evo_ip.get("errors"):
        evo_ip_lines.append(f"| errors | {'; '.join(evo_ip['errors'])} | |")

    evo_ax = science_audit.get("evolutive_raxis_drift") or {}
    evo_ax_lines = [
        f"| status | {evo_ax.get('status', '—')} | preferred soft metric when Ip is clamped |",
        f"| ok | {evo_ax.get('ok')} | |",
        f"| n | {evo_ax.get('n', '—')} | |",
        f"| max drift [m] | {evo_ax.get('max_drift_m', '—')} | vs IC axis |",
        f"| final drift [m] | {evo_ax.get('final_drift_m', '—')} | |",
        f"| threshold [m] | {evo_ax.get('threshold_m', '—')} | abort_when_axis_drift_m |",
        f"| early_stop drift [m] | {evo_ax.get('early_stop_drift_m', '—')} | |",
    ]
    if evo_ax.get("errors"):
        evo_ax_lines.append(f"| errors | {'; '.join(evo_ax['errors'])} | |")

    pvg = science_audit.get("planner_voltage_gap") or {}
    pvg_lines = [
        f"| available | {pvg.get('available')} | |",
        f"| overall | {pvg.get('overall_status', '—')} | {pvg.get('overall_status_label') or 'sign mismatch = YELLOW'} |",
        f"| I-track RMS [A] | {pvg.get('mean_i_track_rms_A', '—')} | primary planner success metric |",
        f"| plan−dyn RMS [V] | {pvg.get('mean_rms_plan_minus_dyn_V', '—')} | ≪ ΔV ⇒ active-only gap |",
        f"| ΔV RMS measured [V] | {pvg.get('residual_rms_mean_measured_V', '—')} | annex (not I-plan failure) |",
        f"| n sign mismatch | {pvg.get('n_sign_mismatch', pvg.get('n_polarity_suspect', '—'))} | YELLOW — cite map before flip |",
        f"| n active-only gap | {pvg.get('n_active_only_gap', pvg.get('n_model_gap_expected', '—'))} | RI+L dI/dt vs terminal V |",
        f"| n same-sign gap | {pvg.get('n_same_sign_model_gap', '—')} | Solenoid early bias ≠ p1 flip |",
    ]

    readme = "\n".join(
        [
            f"SHOT {shot} — Fair-MAST → FreeGSNKE run index",
            "=" * 48,
            "",
            f"Status: {status}",
            f"Created (UTC): {created}",
            f"Window: {t_start} .. {t_end} s" if t_start is not None else "Window: (see inputs/window.json)",
            "",
            "Start with 01_summary/SUMMARY.md (science first), then 04_efit_compare/,",
            "then 03_reconstruction/metrics/ and evolutive Ip residual.",
            "Primary entry file: 00_START_HERE.txt",
            "",
            "How to read this folder",
            "-----------------------",
            "  00_START_HERE.txt               expert reading order",
            "  01_summary/                     science audit + SUMMARY",
            "  02_measured_data/               FAIR-MAST experimental pack",
            "  03_reconstruction/              FreeGSNKE metrics/GIFs/evolutive/dumps",
            "  04_efit_compare/                vs FAIR-MAST EFIT++ archive (ADR-002)",
            "  05_downstream/                  optional TORAX GEQDSK (ADR-001)",
            "  06_authorities/                 contracts + provenance",
            "  07_planner/                     optional GSPulse-style planner (ADR-004)",
            "  08_gsfit/                       optional GSFit live peer (ADR-006)",
            "  inputs/                         tooling CSVs (FreeGSNKE scripts)",
            "  manifest.json                   stage log + blocking_errors",
            "",
            "Modes (from freegsnke_execution):",
            *(
                [f"  - {k}: {v}" for k, v in sorted(exec_st.items())]
                if exec_st
                else ["  - (none recorded)"]
            ),
            "",
            "Known limitations",
            "-----------------",
            *("  - " + lim for lim in _KNOWN_LIMITATIONS),
            "",
        ]
    )
    (run_dir / "00_README.txt").write_text(readme, encoding="utf-8")
    if not (run_dir / "00_START_HERE.txt").exists():
        (run_dir / "00_START_HERE.txt").write_text(readme, encoding="utf-8")

    summary_md = "\n".join(
        [
            f"# Shot {shot} summary",
            "",
            f"- **Status:** `{status}`",
            f"- **UTC:** `{created}`",
            f"- **Formed-plasma window:** `{t_start}` … `{t_end}` s",
            f"- **Modes:** {', '.join(f'{k}={v}' for k, v in sorted(exec_st.items())) or '(none)'}",
            f"- **Reconstruction solve_mode:** `{rq.get('overall_solve_mode')}` "
            f"(hint `{rq.get('science_tier_hint')}`; "
            f"inverse={rq.get('n_inverse_converged')}, "
            f"forward_gs={rq.get('n_forward_gs_fallback')}, "
            f"skipped={rq.get('n_skipped')})",
            f"- **Inverse shape gate:** accepted={shape_gate.get('n_shape_accepted', '—')}, "
            f"GS-ok/shape-unverified={shape_gate.get('n_gs_ok_shape_unverified', '—')}, "
            f"DN-missing-X={shape_gate.get('n_dn_missing_xpoints', '—')} "
            f"(audits={shape_gate.get('n_with_audit', '—')})",
            f"- **Static Forward:** converged={fwd_gate.get('n_converged', '—')}/"
            f"{fwd_gate.get('n_times', '—')} "
            f"(produced={fwd_gate.get('n_ok', '—')}, "
            f"max_iter={fwd_gate.get('n_completed_max_iter', '—')}, "
            f"skipped={fwd_gate.get('n_skipped', '—')}) "
            f"ic_psi={fwd_gate.get('ic_psi_used') or '—'} "
            f"window_currents={fwd_gate.get('window_currents') or '—'} "
            f"profile={fwd_gate.get('profile_source_requested') or (fwd_gate.get('profile_sources_used') or ['—'])}",
            "",
            "## Presentation advisories",
            "",
            *(
                [f"- {it}" for it in (advisories.get("items") or [])]
                if advisories.get("items")
                else ["- (none — Inverse shape accepted and no high EFIT LCFS residual flagged)"]
            ),
            "",
            "## Science residuals (primary)",
            "",
            "### Probe contract metrics",
            "",
            "| Quantity | Value | Notes |",
            "|----------|-------|-------|",
            *_metrics_rows(manifest, run_dir),
            "",
            "### Inverse shape acceptance (GS stop ≠ DN success)",
            "",
            f"- **Available:** `{shape_gate.get('available')}`",
            f"- **t0 status:** `{(shape_gate.get('t0') or {}).get('status')}` / "
            f"shape=`{(shape_gate.get('t0') or {}).get('shape_status')}` "
            f"(constrain_loss=`{(shape_gate.get('t0') or {}).get('constrain_loss_final')}`)",
            f"- **Note:** {shape_gate.get('note', '')}",
            "",
            "### Static Forward (measured-PF replay)",
            "",
            f"- **Available:** `{fwd_gate.get('available')}`",
            f"- **Window solves:** converged={fwd_gate.get('n_converged')} "
            f"max_iter={fwd_gate.get('n_completed_max_iter')} "
            f"produced={fwd_gate.get('n_ok')} skipped={fwd_gate.get('n_skipped')} "
            f"n_times={fwd_gate.get('n_times')}",
            f"- **t0 IC ψ:** `{fwd_gate.get('ic_psi_used')}`",
            f"- **Profile source:** requested=`{fwd_gate.get('profile_source_requested')}` "
            f"used=`{fwd_gate.get('profile_sources_used')}`",
            f"- **Note:** {fwd_gate.get('note', '')}",
            "",
            "### Evolutive Ip vs measured FAIR-MAST Ip",
            "",
            "| Quantity | Value | Notes |",
            "|----------|-------|-------|",
            *evo_ip_lines,
            "",
            "### Evolutive Raxis drift (soft physics metric)",
            "",
            "| Quantity | Value | Notes |",
            "|----------|-------|-------|",
            *evo_ax_lines,
            "",
            "### Planner voltage gap (I-track vs terminal V)",
            "",
            "| Quantity | Value | Notes |",
            "|----------|-------|-------|",
            *pvg_lines,
            "",
            f"_{pvg.get('note', '')}_",
            "",
            "### Ohmic / measured voltage drive inventory",
            "",
            f"- **Measured V circuits:** {meas_v}",
            f"- **from_current_ohmic (I×R):** {ohmic_list}",
            f"- **Note:** {ohmic.get('uncertainty_note', '')}",
            "",
            f"### Passives: `{passives.get('status', 'unknown')}` "
            f"(n_components={passives.get('n_components', 0)})",
            "",
            f"{passives.get('note', '')}",
            "",
            "## Phase timeline (window-derived)",
            "",
            "| Phase | t_start [s] | t_end [s] |",
            "|-------|-------------|-----------|",
            *phase_lines,
            "",
            f"_{phases.get('note', '')}_",
            "",
            "## Key paths",
            "",
            "| Artifact | Path |",
            "|----------|------|",
            "| Start here | `00_START_HERE.txt` |",
            "| Science audit | `01_summary/science_audit.json` |",
            "| EFIT++ compare | `04_efit_compare/COMPARE.md` |",
            "| Manifest | `manifest.json` |",
            "| Window | `inputs/window.json` |",
            "| Phase timeline | `inputs/phase_timeline.json` |",
            "| PF currents | `inputs/pf_currents.csv` |",
            "| PF voltages (mapped) | `inputs/pf_voltages.csv` |",
            "| Metrics | `03_reconstruction/metrics/reconstruction_metrics.json` |",
            "| Evolutive Ip residual | `03_reconstruction/evolutive/ip_residual.csv` |",
            "| Evolutive Raxis drift | `03_reconstruction/evolutive/raxis_drift.csv` |",
            "| Planner voltage model gap | `07_planner/voltage_model_gap.json` |",
            "| Inverse dump | `inverse_dump.pkl` (run root) |",
            "| Measured data | `02_measured_data/` |",
            "| Authorities | `06_authorities/` |",
            "| Logs | `logs/` |",
            "",
            "## EFIT++ archive compare (ADR-002)",
            "",
            "See `04_efit_compare/COMPARE.md` and `04_efit_compare/shape_scorecard.csv` when `compare_efit_archive=true`.",
            "Mode: **reconstruction_vs_archive** (not Pentland forward-replay). ψ in **Wb/2π**.",
            "Labels are FreeGSNKE vs FAIR-MAST EFIT++ archive — not efit-ai / Py-EFIT.",
            "",
            "## Presentation annex (GIFs)",
            "",
            *(
                [f"- `{k}`: `{v}`" for k, v in sorted(gifs.items())]
                if gifs
                else ["- (none — enable write_equilibrium_gifs)"]
            ),
            "",
            "_GIFs are not a substitute for residual metrics._",
            "",
            "## Authorities",
            "",
            *(auth_lines or ["- (see 06_authorities/ and inputs/)"]),
            "",
            "## Blocking errors",
            "",
            *(
                [f"- `{e}`" for e in blocking]
                if blocking
                else ["- (none)"]
            ),
            "",
            "## Known limitations",
            "",
            *("- " + lim for lim in _KNOWN_LIMITATIONS),
            "",
        ]
    )
    (summary_dir / "SUMMARY.md").write_text(summary_md, encoding="utf-8")

    summary_json = {
        "shot": int(shot),
        "status": status,
        "created_utc": created,
        "window": {"t_start": t_start, "t_end": t_end},
        "modes": exec_st,
        "science_audit": science_audit,
        "presentation_gifs": gifs,
        "blocking_errors": list(blocking),
        "known_limitations": list(_KNOWN_LIMITATIONS),
    }
    (summary_dir / "SUMMARY.json").write_text(json.dumps(summary_json, indent=2) + "\n", encoding="utf-8")

    timeline_lines = ["stage_log (utc-ordered as recorded)", "-" * 40]
    for st in stages:
        if not isinstance(st, dict):
            continue
        name = st.get("stage") or st.get("name") or "?"
        ok = st.get("ok")
        timeline_lines.append(f"{'[OK]' if ok else '[--]'} {name}")
    (summary_dir / "timeline.txt").write_text("\n".join(timeline_lines) + "\n", encoding="utf-8")

    return {
        "readme": "00_README.txt",
        "summary_md": "01_summary/SUMMARY.md",
        "summary_json": "01_summary/SUMMARY.json",
        "timeline": "01_summary/timeline.txt",
        "science_audit": "01_summary/science_audit.json",
    }
