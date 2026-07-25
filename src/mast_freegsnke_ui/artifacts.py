"""Read-only loaders over SHOT/<N>/ artifacts for the Dash UI."""
from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import zipfile
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


DOWNLOAD_EXTS = {".png", ".gif", ".csv", ".json", ".md", ".txt", ".npz", ".pkl"}
_IMAGE_EXTS = {".png", ".gif", ".jpg", ".jpeg", ".webp"}


def _safe_json(path: Path) -> Optional[Dict[str, Any]]:
    """Load JSON without holding a long lock (Windows replace vs UI poll).

    Prefer a single ``read_bytes`` so the file handle is released immediately;
    partial/torn reads during a rare non-atomic fallback write return None.
    """
    if not path.is_file():
        return None
    try:
        raw = path.read_bytes()
        obj = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def list_shot_dirs(runs_dir: Path) -> List[int]:
    """Return numeric SHOT/<N>/ folders (fast — no deep marker probes)."""
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []
    shots: List[int] = []
    try:
        for name in os.listdir(runs_dir):
            if not name.isdigit():
                continue
            try:
                if (runs_dir / name).is_dir():
                    shots.append(int(name))
            except OSError:
                continue
    except OSError:
        return []
    return sorted(shots, reverse=True)


def run_dir_for(runs_dir: Path, shot: int) -> Path:
    return Path(runs_dir) / str(int(shot))


def load_progress(run_dir: Path) -> Optional[Dict[str, Any]]:
    return _safe_json(Path(run_dir) / "progress.json")


def load_manifest(run_dir: Path) -> Optional[Dict[str, Any]]:
    return _safe_json(Path(run_dir) / "manifest.json")


def load_summary(run_dir: Path) -> Optional[Dict[str, Any]]:
    return _safe_json(Path(run_dir) / "01_summary" / "SUMMARY.json")


def load_science_audit(run_dir: Path) -> Optional[Dict[str, Any]]:
    return _safe_json(Path(run_dir) / "01_summary" / "science_audit.json")


def load_metrics(run_dir: Path) -> Optional[Dict[str, Any]]:
    run_dir = Path(run_dir)
    for rel in (
        "03_reconstruction/metrics/reconstruction_metrics.json",
        "metrics/reconstruction_metrics.json",
    ):
        obj = _safe_json(run_dir / rel)
        if obj is not None:
            return obj
    return None


def load_efit_compare(run_dir: Path) -> Optional[Dict[str, Any]]:
    run_dir = Path(run_dir)
    for rel in ("04_efit_compare/COMPARE.json", "efit_compare/COMPARE.json"):
        obj = _safe_json(run_dir / rel)
        if obj is not None:
            return obj
    return None


def load_shape_scorecard(run_dir: Path) -> Optional[Dict[str, Any]]:
    return _safe_json(Path(run_dir) / "04_efit_compare" / "shape_scorecard.json")


def load_summary_markdown(run_dir: Path) -> Optional[str]:
    p = Path(run_dir) / "01_summary" / "SUMMARY.md"
    if not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return None


def _is_reparse_point(path: Path) -> bool:
    """True for symlinks / Windows junctions (directories we must not walk into recursively)."""
    try:
        if path.is_symlink():
            return True
        if os.name == "nt":
            st = path.lstat()
            return bool(getattr(st, "st_file_attributes", 0) & 0x400)
    except OSError:
        return False
    return False


def _open_dir(folder: Path) -> Optional[Path]:
    """Return a listable directory, resolving a single junction hop when needed."""
    folder = Path(folder)
    try:
        if not folder.exists():
            return None
        if folder.is_dir():
            # Junctions are dirs — resolve once so listdir sees real files.
            try:
                return folder.resolve()
            except OSError:
                return folder
    except OSError:
        return None
    return None


def _list_images_flat(folder: Path, *, exts: Optional[set[str]] = None, limit: int = 48) -> List[Path]:
    """Fast image listing for a known plot folder (follows one junction hop)."""
    opened = _open_dir(folder)
    if opened is None:
        return []
    want = exts or {".png"}
    out: List[Path] = []
    try:
        names = sorted(os.listdir(opened))
    except OSError:
        return []
    for name in names:
        suf = Path(name).suffix.lower()
        if suf not in want:
            continue
        fp = opened / name
        try:
            if fp.is_file():
                out.append(fp)
        except OSError:
            continue
        if len(out) >= limit:
            break
    return out


def _collect_images(root: Path, patterns: Tuple[str, ...] = ("*.png", "*.gif"), *, max_depth: int = 2, limit: int = 64) -> List[Path]:
    """Shallow image collect; skips history/ and nested junctions."""
    opened = _open_dir(root)
    if opened is None:
        return []
    out: List[Path] = []
    root_depth = len(opened.parts)
    try:
        for dirpath, dirnames, filenames in os.walk(opened, topdown=True, followlinks=False):
            base = Path(dirpath)
            depth = len(base.parts) - root_depth
            if depth > max_depth:
                dirnames[:] = []
                continue
            keep: List[str] = []
            for name in dirnames:
                if name in {"history", ".git", "__pycache__", ".multitime_work", "data_cache"}:
                    continue
                child = base / name
                # Avoid descending into nested junctions (cycles / off-tree).
                if _is_reparse_point(child):
                    continue
                keep.append(name)
            dirnames[:] = keep
            for name in filenames:
                if not any(fnmatch(name, pat) for pat in patterns):
                    continue
                fp = base / name
                try:
                    if fp.is_file():
                        out.append(fp)
                except OSError:
                    continue
                if len(out) >= limit:
                    return sorted(out)
    except OSError:
        return []
    return sorted(out)


def _first_images(candidates: Sequence[Path], *, exts: set[str], limit: int = 48) -> List[Path]:
    for c in candidates:
        imgs = _list_images_flat(c, exts=exts, limit=limit)
        if imgs:
            return imgs
        # Fallback: shallow walk when plots live one level deeper than expected.
        pats = tuple(f"*{e}" for e in sorted(exts))
        imgs = _collect_images(c, pats, max_depth=2, limit=limit)
        if imgs:
            return imgs
    return []


def measured_plot_paths(run_dir: Path) -> List[Path]:
    run_dir = Path(run_dir)
    return _first_images(
        [
            run_dir / "02_measured_data" / "05_plots",
            run_dir / "experimental_data" / "05_plots",
            run_dir / "02_measured_data",
            run_dir / "experimental_data",
        ],
        exts={".png"},
        limit=32,
    )


def residual_plot_paths(run_dir: Path) -> List[Path]:
    run_dir = Path(run_dir)
    return _first_images(
        [
            run_dir / "report" / "key_plots",
            run_dir / "03_reconstruction" / "metrics" / "report" / "key_plots",
            run_dir / "metrics" / "report" / "key_plots",
        ],
        exts={".png"},
        limit=32,
    )


def efit_plot_paths(run_dir: Path) -> List[Path]:
    run_dir = Path(run_dir)
    return _first_images(
        [
            run_dir / "04_efit_compare" / "plots",
            run_dir / "efit_compare" / "plots",
        ],
        exts={".png"},
        limit=32,
    )


def gif_paths(run_dir: Path) -> List[Path]:
    run_dir = Path(run_dir)
    out: List[Path] = []
    for rel in (
        "03_reconstruction/presentation",
        "03_reconstruction/evolutive",
        "presentation",
        "evolutive",
    ):
        out.extend(_first_images([run_dir / rel], exts={".gif"}, limit=24))
    seen: set[str] = set()
    uniq: List[Path] = []
    for p in out:
        key = str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def residual_csv_paths(run_dir: Path) -> List[Path]:
    run_dir = Path(run_dir)
    for rel in ("03_reconstruction/metrics", "metrics"):
        d = run_dir / rel
        opened = _open_dir(d)
        if opened is None:
            continue
        try:
            return sorted(opened.glob("residual_*.csv"))
        except OSError:
            continue
    return []


def rel_posix(path: Path, run_dir: Path) -> str:
    """Relative POSIX path for URLs — prefer non-resolve relpath (junction-safe)."""
    path = Path(path)
    run_dir = Path(run_dir)
    try:
        return Path(os.path.relpath(str(path), str(run_dir))).as_posix()
    except ValueError:
        pass
    try:
        return path.resolve().relative_to(Path(run_dir).resolve()).as_posix()
    except (ValueError, OSError):
        return path.name


def safe_resolve_under(run_dir: Path, rel: str) -> Optional[Path]:
    """Resolve ``rel`` under ``run_dir``; reject path traversal."""
    run_dir = Path(run_dir).resolve()
    raw = (rel or "").replace("\\", "/").lstrip("/")
    if not raw or ".." in Path(raw).parts:
        return None
    candidate = (run_dir / raw).resolve()
    try:
        candidate.relative_to(run_dir)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def file_url(shot: int, rel: str, *, download: bool = False, bust: Optional[str] = None) -> str:
    from urllib.parse import quote

    parts = [f"/shot-file/{int(shot)}/{quote(rel.replace(chr(92), '/'), safe='/')}"]
    q: List[str] = []
    if download:
        q.append("download=1")
    if bust:
        q.append(f"v={quote(str(bust))}")
    if q:
        parts.append("?" + "&".join(q))
    return "".join(parts)


def file_url_for_path(shot: int, path: Path, run_dir: Path, *, download: bool = False) -> str:
    rel = rel_posix(path, run_dir)
    bust = None
    try:
        bust = str(int(Path(path).stat().st_mtime_ns))
    except OSError:
        pass
    return file_url(shot, rel, download=download, bust=bust)


def authority_snapshot(run_dir: Path) -> Dict[str, Any]:
    """Presence + short hashes for authorities (read-only; never invents metrology).

    Returns ``{items, matrix, blocking_hint}`` where ``matrix`` lists expected
    authority roles with status present|missing|awaiting for the Authorities tab.
    """
    run_dir = Path(run_dir)
    items: List[Dict[str, Any]] = []
    checks = [
        ("coil_map.resolved", "06_authorities/contracts/coil_map.resolved.json"),
        ("coil_map.resolved (legacy)", "contracts/coil_map.resolved.json"),
        ("voltage_map.sha256", "06_authorities/contracts/voltage_map.sha256.json"),
        ("voltage_map.sha256 (legacy)", "contracts/voltage_map.sha256.json"),
        ("diagnostic_contracts", "06_authorities/contracts/diagnostic_contracts.resolved.json"),
        ("diagnostic_contracts (legacy)", "contracts/diagnostic_contracts.resolved.json"),
        ("evolutive_authority", "inputs/evolutive_authority/evolutive_authority.json"),
        ("execution_authority", "inputs/execution_authority/execution_authority_bundle.json"),
        ("diagnostic_calibration", "06_authorities/diagnostic_calibration/diagnostic_calibration.json"),
        ("diagnostic_calibration (legacy)", "inputs/diagnostic_calibration/diagnostic_calibration.json"),
        ("machine_authority_snapshot", "06_authorities/machine_authority_snapshot/authority_manifest.json"),
        ("machine_authority_snapshot (legacy)", "machine_authority_snapshot/authority_manifest.json"),
        ("provenance hashes", "06_authorities/provenance/file_hashes.json"),
        ("provenance hashes (legacy)", "provenance/file_hashes.json"),
    ]
    seen_roles: set[str] = set()
    present_by_role: Dict[str, Dict[str, Any]] = {}
    for label, rel in checks:
        role = label.split(" (")[0]
        if role in seen_roles:
            continue
        p = run_dir / rel
        if not p.is_file():
            continue
        seen_roles.add(role)
        entry: Dict[str, Any] = {
            "label": role,
            "path": rel.replace("\\", "/"),
            "present": True,
            "rel": rel.replace("\\", "/"),
            "status": "present",
        }
        obj = _safe_json(p)
        if obj:
            for key in ("sha256", "authority_name", "authority_version", "version", "n_channels", "status"):
                if key in obj and obj[key] is not None:
                    val = obj[key]
                    if key == "sha256" and isinstance(val, str) and len(val) > 16:
                        entry["detail"] = f"sha256={val[:16]}…"
                    elif key == "status":
                        entry.setdefault("detail", f"status={val}")
                    else:
                        entry.setdefault("detail", f"{key}={val}")
        items.append(entry)
        present_by_role[role] = entry

    # Expected matrix roles (expert traffic light) — missing ≠ invent.
    expected = (
        "machine_authority_snapshot",
        "coil_map.resolved",
        "voltage_map.sha256",
        "diagnostic_contracts",
        "evolutive_authority",
        "execution_authority",
        "diagnostic_calibration",
        "provenance hashes",
    )
    matrix: List[Dict[str, Any]] = []
    for role in expected:
        if role in present_by_role:
            matrix.append(dict(present_by_role[role]))
            continue
        status = "missing"
        hint = "Populate declared JSON authority — do not invent metrology."
        if role == "diagnostic_calibration":
            status = "awaiting"
            hint = (
                "Optional until mirnov/saddle/omaha synthesis is required; "
                "populate configs/diagnostic_calibration.json with cited scale/sign/source."
            )
        matrix.append(
            {
                "label": role,
                "path": None,
                "rel": None,
                "present": False,
                "status": status,
                "detail": hint,
            }
        )

    missing_hint = None
    man = load_manifest(run_dir) or {}
    blocking = list(man.get("blocking_errors") or [])
    prog = load_progress(run_dir) or {}
    blocking.extend(list(prog.get("blocking_errors") or []))
    auth_block = [
        b
        for b in blocking
        if any(
            tok in str(b).lower()
            for tok in ("authority", "coil_map", "voltage_map", "diagnostic_calibration", "contract")
        )
    ]
    if auth_block:
        missing_hint = (
            "Blocking authority error — fix machine_authority/ or contracts; "
            "do not invent metrology. " + "; ".join(str(x) for x in auth_block[:3])
        )
    return {"items": items, "matrix": matrix, "blocking_hint": missing_hint}


def calibration_await_rows(run_dir: Path) -> List[Dict[str, Any]]:
    """Channels / families awaiting diagnostic_calibration (from run reports — never invent)."""
    run_dir = Path(run_dir)
    rows: List[Dict[str, Any]] = []
    for rel in (
        "experimental_data_report.json",
        "02_measured_data/00_index/optional_diagnostics.json",
        "01_summary/science_audit.json",
    ):
        obj = _safe_json(run_dir / rel)
        if not obj:
            continue
        # experimental_data_report style
        for fam in ("mirnov", "saddle", "omaha", "magnetics"):
            node = obj.get(fam) if isinstance(obj, dict) else None
            if isinstance(node, dict):
                st = str(node.get("status") or node.get("calibration_status") or "")
                if "await" in st.lower() or "uncalibrat" in st.lower() or st == "awaiting_authority":
                    rows.append(
                        {
                            "family": fam,
                            "status": st or "awaiting_authority",
                            "source": rel,
                            "hint": "Populate configs/diagnostic_calibration.json (cited scale/sign/source).",
                        }
                    )
        audit_cal = obj.get("diagnostic_calibration") if isinstance(obj, dict) else None
        if isinstance(audit_cal, dict):
            st = str(audit_cal.get("status") or "")
            if st and st not in {"populated", "ok", "applied"}:
                rows.append(
                    {
                        "family": "diagnostic_calibration",
                        "status": st,
                        "source": rel,
                        "hint": audit_cal.get("note")
                        or "Awaiting cited calibration factors — do not invent V→T.",
                    }
                )
        warnings = obj.get("warnings") if isinstance(obj, dict) else None
        if isinstance(warnings, list):
            for w in warnings:
                ws = str(w)
                if "calibrat" in ws.lower() or "uncalibrat" in ws.lower() or "await" in ws.lower():
                    rows.append(
                        {
                            "family": "catalog",
                            "status": "warning",
                            "source": rel,
                            "hint": ws[:200],
                        }
                    )
    # De-dupe by family+status
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        key = f"{r.get('family')}|{r.get('status')}|{r.get('hint')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out[:24]


def file_to_data_uri(path: Path) -> Optional[str]:
    path = Path(path)
    if not path.is_file():
        return None
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "application/octet-stream"
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def overview_kpis(run_dir: Path) -> Dict[str, Any]:
    """Compact KPI dict for the overview strip."""
    run_dir = Path(run_dir)
    summary = load_summary(run_dir) or {}
    man = load_manifest(run_dir) or {}
    progress = load_progress(run_dir) or {}
    audit = load_science_audit(run_dir) or summary.get("science_audit") or {}
    metrics = load_metrics(run_dir) or {}
    efit = load_efit_compare(run_dir) or {}
    window = summary.get("window") or man.get("time_window") or {}
    blocking = list(summary.get("blocking_errors") or man.get("blocking_errors") or progress.get("blocking_errors") or [])
    evo = audit.get("evolutive_ip") if isinstance(audit, dict) else {}
    status = summary.get("status") or man.get("status") or progress.get("status") or "unknown"
    return {
        "shot": summary.get("shot") or man.get("shot") or run_dir.name,
        "status": status,
        "t_start": window.get("t_start"),
        "t_end": window.get("t_end"),
        "n_scored": metrics.get("n_scored"),
        "metrics_ok": metrics.get("ok"),
        "efit_ok": efit.get("ok"),
        "evolutive_ok": evo.get("ok") if isinstance(evo, dict) else None,
        "evolutive_rms_A": evo.get("rms_A") if isinstance(evo, dict) else None,
        "blocking_n": len(blocking),
        "blocking": blocking[:8],
        "modes": summary.get("modes") or {},
        "n_stages": len(progress.get("stage_log") or man.get("stage_log") or []),
    }


_COMPARE_NUMERIC_KEYS = (
    "t_start",
    "t_end",
    "window_dt",
    "n_scored",
    "evolutive_rms_A",
    "blocking_n",
)


def _kpi_delta(a: Any, b: Any) -> Any:
    """B − A for numeric KPIs; None when either side is missing/non-numeric.

    Booleans are excluded (``float(True) == 1.0`` would invent a fake delta).
    """
    try:
        if a is None or b is None:
            return None
        if isinstance(a, bool) or isinstance(b, bool):
            return None
        return float(b) - float(a)
    except (TypeError, ValueError):
        return None


def _window_duration_s(kpis: Dict[str, Any]) -> Optional[float]:
    """Formed-plasma window length [s] from t_end − t_start when both finite."""
    try:
        t0 = kpis.get("t_start")
        t1 = kpis.get("t_end")
        if t0 is None or t1 is None:
            return None
        return float(t1) - float(t0)
    except (TypeError, ValueError):
        return None


def compare_scorecard(
    run_a: Optional[Path],
    run_b: Optional[Path],
    *,
    shot_a: Optional[int] = None,
    shot_b: Optional[int] = None,
) -> Dict[str, Any]:
    """Paired KPIs for browse-only shot A vs B (no invented metrology).

    Returns ``{shot_a, shot_b, a, b, rows}`` where each row is
    ``{key, label, a, b, delta}``. Missing run dirs yield empty KPI dicts.
    """
    a_present = run_a is not None and Path(run_a).is_dir()
    b_present = run_b is not None and Path(run_b).is_dir()
    ka = overview_kpis(Path(run_a)) if a_present else {}
    kb = overview_kpis(Path(run_b)) if b_present else {}
    if shot_a is not None and a_present:
        ka = {**ka, "shot": int(shot_a)}
    if shot_b is not None and b_present:
        kb = {**kb, "shot": int(shot_b)}
    if a_present:
        ka = {**ka, "window_dt": _window_duration_s(ka)}
    if b_present:
        kb = {**kb, "window_dt": _window_duration_s(kb)}

    labels = (
        ("status", "Status"),
        ("t_start", "Window t_start [s]"),
        ("t_end", "Window t_end [s]"),
        ("window_dt", "Window Δt [s]"),
        ("n_scored", "Contracts scored"),
        ("metrics_ok", "Metrics ok"),
        ("evolutive_ok", "Evolutive Ip ok"),
        ("evolutive_rms_A", "Evolutive Ip RMS [A]"),
        ("efit_ok", "EFIT archive ok"),
        ("blocking_n", "Blocking errors"),
    )
    rows: List[Dict[str, Any]] = []
    for key, label in labels:
        va = ka.get(key)
        vb = kb.get(key)
        delta = _kpi_delta(va, vb) if key in _COMPARE_NUMERIC_KEYS else None
        rows.append({"key": key, "label": label, "a": va, "b": vb, "delta": delta})

    # Modes as a compact string row (no numeric delta).
    def _modes_txt(k: Dict[str, Any]) -> Optional[str]:
        modes = k.get("modes") or {}
        if not isinstance(modes, dict) or not modes:
            return None
        return ", ".join(f"{mk}={mv}" for mk, mv in modes.items())

    rows.insert(
        1,
        {
            "key": "modes",
            "label": "Modes",
            "a": _modes_txt(ka),
            "b": _modes_txt(kb),
            "delta": None,
        },
    )
    return {
        "shot_a": int(shot_a) if shot_a is not None else (ka.get("shot") if a_present else None),
        "shot_b": int(shot_b) if shot_b is not None else (kb.get("shot") if b_present else None),
        "a_present": a_present,
        "b_present": b_present,
        "a": ka,
        "b": kb,
        "rows": rows,
    }


def pair_paths_by_name(paths_a: List[Path], paths_b: List[Path]) -> List[Dict[str, Optional[Path]]]:
    """Align two path lists by basename for side-by-side display (A-only / B-only allowed)."""
    map_a = {p.name: p for p in paths_a}
    map_b = {p.name: p for p in paths_b}
    names = sorted(set(map_a) | set(map_b))
    return [{"name": n, "a": map_a.get(n), "b": map_b.get(n)} for n in names]


def overview_text(run_dir: Path) -> str:
    """Human-readable overview from SUMMARY.json / manifest / science_audit."""
    k = overview_kpis(run_dir)
    lines = [
        f"Shot: {k['shot']}",
        f"Status: {k['status']}",
        (
            f"Window: [{k['t_start']}, {k['t_end']}] s"
            if k["t_start"] is not None or k["t_end"] is not None
            else "Window: (unknown)"
        ),
    ]
    modes = k.get("modes") or {}
    if modes:
        lines.append("Modes: " + ", ".join(f"{a}={b}" for a, b in modes.items()))
    if k.get("n_scored") is not None:
        lines.append(f"Contracts scored: {k['n_scored']} (ok={k.get('metrics_ok')})")
    if k.get("efit_ok") is not None:
        lines.append(f"EFIT archive compare ok={k['efit_ok']}")
    if k.get("evolutive_ok") is not None:
        lines.append(f"Evolutive Ip: ok={k['evolutive_ok']} rms_A={k.get('evolutive_rms_A')}")
    if k["blocking"]:
        lines.append("Blocking errors:")
        for e in k["blocking"]:
            lines.append(f"  - {e}")
    else:
        lines.append("Blocking errors: (none)")
    md = Path(run_dir) / "01_summary" / "SUMMARY.md"
    if md.is_file():
        lines.append("")
        lines.append(f"(Full write-up: {md.as_posix()})")
    return "\n".join(lines)


def metrics_table_rows(metrics: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not metrics:
        return []
    per = metrics.get("per_contract") or {}
    rows: List[Dict[str, Any]] = []
    if isinstance(per, dict):
        for name, stats in per.items():
            if not isinstance(stats, dict):
                continue
            rows.append(
                {
                    "contract": name,
                    "rms": stats.get("rms"),
                    "mae": stats.get("mae"),
                    "max_abs": stats.get("max_abs"),
                    "n": stats.get("n"),
                }
            )
    return rows


_PREFERRED_DOWNLOADS = (
    "00_START_HERE.txt",
    "01_summary/SUMMARY.md",
    "01_summary/SUMMARY.json",
    "01_summary/science_audit.json",
    "manifest.json",
    "progress.json",
    "03_reconstruction/metrics/reconstruction_metrics.json",
    "04_efit_compare/COMPARE.json",
    "04_efit_compare/COMPARE.md",
    "04_efit_compare/shape_scorecard.json",
    "04_efit_compare/shape_scorecard.csv",
)


def catalog_quick(run_dir: Path) -> List[Dict[str, Any]]:
    """Known summary/metrics files only — no tree walks (safe for Overview)."""
    run_dir = Path(run_dir)
    items: List[Dict[str, Any]] = []
    for rel in _PREFERRED_DOWNLOADS:
        p = run_dir / rel
        try:
            if not p.is_file():
                continue
            items.append(
                {
                    "rel": rel.replace("\\", "/"),
                    "name": p.name,
                    "kind": p.suffix.lstrip(".").lower() or "file",
                    "bytes": p.stat().st_size,
                    "group": "summary",
                }
            )
        except OSError:
            continue
    return items


def catalog_downloadables(run_dir: Path) -> List[Dict[str, Any]]:
    """Flat catalog of user-facing downloadable artifacts under a run."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return []
    items = catalog_quick(run_dir)
    seen = {it["rel"] for it in items}
    groups = [
        ("plots", measured_plot_paths(run_dir) + residual_plot_paths(run_dir) + efit_plot_paths(run_dir)),
        ("gifs", gif_paths(run_dir)),
        ("csv", residual_csv_paths(run_dir)),
    ]
    for rel_dir in ("02_measured_data", "04_efit_compare", "03_reconstruction/metrics"):
        d = _open_dir(run_dir / rel_dir)
        if d is None:
            continue
        try:
            for name in os.listdir(d):
                if not name.lower().endswith(".csv"):
                    continue
                groups.append(("csv", [d / name]))
        except OSError:
            continue

    for group, paths in groups:
        for p in paths:
            try:
                if not p.is_file():
                    continue
            except OSError:
                continue
            suf = p.suffix.lower()
            if group == "gifs" and suf != ".gif":
                continue
            if group == "plots" and suf not in _IMAGE_EXTS:
                continue
            if group == "csv" and suf != ".csv":
                continue
            if suf not in DOWNLOAD_EXTS and group not in {"plots", "gifs", "csv"}:
                continue
            rel = rel_posix(p, run_dir)
            if rel in seen or rel.startswith(".."):
                continue
            # Only serve paths that safe_resolve_under accepts.
            if safe_resolve_under(run_dir, rel) is None:
                continue
            seen.add(rel)
            try:
                nbytes = p.stat().st_size
            except OSError:
                nbytes = 0
            items.append(
                {
                    "rel": rel,
                    "name": p.name,
                    "kind": suf.lstrip(".") or "file",
                    "bytes": nbytes,
                    "group": group,
                }
            )
    return items


def build_run_zip_bytes(
    run_dir: Path,
    *,
    include_groups: Optional[Sequence[str]] = None,
    max_files: int = 400,
) -> bytes:
    """Zip selected downloadable artifacts for local save."""
    run_dir = Path(run_dir)
    wanted = set(include_groups) if include_groups else None
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in catalog_downloadables(run_dir):
            if wanted is not None and item["group"] not in wanted:
                continue
            if n >= max_files:
                break
            path = safe_resolve_under(run_dir, item["rel"])
            if path is None:
                continue
            zf.write(path, arcname=f"{run_dir.name}/{item['rel']}")
            n += 1
    return buf.getvalue()


def results_fingerprint(run_dir: Optional[Path]) -> str:
    """Stable-ish fingerprint so UI refreshes results only when content changes."""
    if run_dir is None or not Path(run_dir).is_dir():
        return ""
    run_dir = Path(run_dir)
    parts: List[str] = [run_dir.name]
    for rel in ("progress.json", "manifest.json", "01_summary/SUMMARY.json", "01_summary/SUMMARY.md"):
        p = run_dir / rel
        try:
            if p.is_file():
                st = p.stat()
                parts.append(f"{rel}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(rel)
    return "|".join(parts)
