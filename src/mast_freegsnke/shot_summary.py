"""Expert-facing SHOT/<N>/ index layer (00_README + 01_summary).

Operational paths (inputs/, synthetic/, metrics/, logs/, manifest.json, *.py)
remain at the run root for tooling stability. This module only adds the
human/expert overlay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


_KNOWN_LIMITATIONS = [
    "Structural machine is classic MAST built from FAIR-MAST Level-2 filaments (machine_authority/; see FREEGSNKE_MACHINE_PROVENANCE.json) — not FreeGSNKE MAST-U pickles.",
    "Limiter/wall = FAIR-MAST wall.zarr limiter_r/z (EFIT limiter geometry) — not surveyed CAD vessel; not a flux-loop computational proxy.",
    "No FreeGSNKE passives: Level-2 pf_passive has parallelogram geometry but no resistivity (do not invent resistivity).",
    "FAIR-MAST Level-2 supplies measured voltages (p1/p2/p4/p5 in V) as primary evolutive drive; p2 is applied identically to P2_inner and P2_outer (declared same-V policy).",
    "P3 and P6: no usable measured PF voltage in public L1/L2 -> from_current_ohmic (I*R with FreeGSNKE coil_resist after load).",
    "Active-coil resistivity is FreeGSNKE copper default 1.55e-8 (declared material constant; Level-2 does not publish coil resistivity).",
    "Profile alpha_m/alpha_n/fvac are held from the inverse IC; optional scale_paxis_with_ip is a declared Ip scaling law (default off) — never invented profile numbers.",
    "Contract residual metrics score only families with honest channel identity + units; uncalibrated mirnov/saddle/omaha stay audit-only until calibration authority is populated.",
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
    # Also record skip
    if fe.get("skipped"):
        by_label["skipped"] = str(fe.get("skipped"))
    return by_label


def _metrics_table(manifest: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    m = manifest.get("reconstruction_metrics")
    if not isinstance(m, dict):
        lines.append("| (none) | — | — |")
        return lines
    lines.append(f"| n_scored | {m.get('n_scored', '—')} | |")
    lines.append(f"| n_skipped_all_nan | {m.get('n_skipped_all_nan', '—')} | |")
    ok = m.get("ok")
    lines.append(f"| metrics_ok | {ok} | |")
    # Per-family RMS if present
    families = m.get("families") or m.get("by_family") or {}
    if isinstance(families, dict):
        for fam, stats in sorted(families.items()):
            if isinstance(stats, dict):
                rms = stats.get("rms") or stats.get("RMS") or stats.get("rms_mean")
                lines.append(f"| {fam} RMS | {rms if rms is not None else '—'} | |")
    return lines


def write_shot_expert_overlay(
    run_dir: Path,
    *,
    shot: int,
    manifest: Optional[Dict[str, Any]] = None,
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

    # Authority hashes (best-effort)
    auth_lines: List[str] = []
    for rel in [
        "contracts/voltage_map.sha256.json",
        "contracts/coil_map.resolved.json",
        "provenance/hashes.json",
        "machine_authority_snapshot/authority_manifest.json",
    ]:
        p = run_dir / rel
        if p.exists():
            auth_lines.append(f"- `{rel}` present")
    vm_hash = _safe_load_json(run_dir / "contracts" / "voltage_map.sha256.json")
    if vm_hash and vm_hash.get("sha256"):
        auth_lines.append(f"- voltage_map sha256: `{vm_hash['sha256'][:16]}…`")

    readme = "\n".join(
        [
            f"SHOT {shot} — Fair-MAST → FreeGSNKE run index",
            "=" * 48,
            "",
            f"Status: {status}",
            f"Created (UTC): {created}",
            f"Window: {t_start} .. {t_end} s" if t_start is not None else "Window: (see inputs/window.json)",
            "",
            "How to read this folder",
            "-----------------------",
            "Operational tooling paths (stable; used by pipeline/CLI):",
            "  inputs/              experimental CSVs + authorities snapshots",
            "  experimental_data/   categorized FAIR-MAST CSV + professional plots",
            "  synthetic/           FreeGSNKE synthetic probe traces",
            "  metrics/             residual scores",
            "  logs/                FreeGSNKE stdout/stderr",
            "  manifest.json        stage log + blocking_errors + provenance pointers",
            "  inverse_run.py / forward_run.py / evolutive_run.py",
            "  inverse_dump.pkl     IC for forward + evolutive",
            "",
            "Expert-facing overlay (this layer):",
            "  00_README.txt        this index",
            "  01_summary/          SUMMARY.md + timeline.txt",
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

    summary_md = "\n".join(
        [
            f"# Shot {shot} summary",
            "",
            f"- **Status:** `{status}`",
            f"- **UTC:** `{created}`",
            f"- **Window:** `{t_start}` … `{t_end}` s",
            f"- **Modes:** {', '.join(f'{k}={v}' for k, v in sorted(exec_st.items())) or '(none)'}",
            "",
            "## Key metrics",
            "",
            "| Quantity | Value | Notes |",
            "|----------|-------|-------|",
            *_metrics_table(manifest),
            "",
            "## Key paths",
            "",
            "| Artifact | Path |",
            "|----------|------|",
            "| Manifest | `manifest.json` |",
            "| Window | `inputs/window.json` |",
            "| PF currents | `inputs/pf_currents.csv` |",
            "| PF voltages (raw) | `inputs/pf_voltages_raw.csv` |",
            "| PF voltages (mapped) | `inputs/pf_voltages.csv` |",
            "| Inverse dump | `inverse_dump.pkl` |",
            "| Evolutive history | `evolutive/` |",
            "| Metrics | `metrics/reconstruction_metrics.json` |",
            "| Logs | `logs/` |",
            "",
            "## Authorities",
            "",
            *(auth_lines or ["- (see contracts/ and provenance/)"]),
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

    # Compact JSON twin for tooling
    summary_json = {
        "shot": int(shot),
        "status": status,
        "created_utc": created,
        "window": {"t_start": t_start, "t_end": t_end},
        "modes": exec_st,
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
    }
