"""Level-2 measured-data helpers for the expert UI (catalog, CSVs, cache status)."""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from mast_freegsnke_ui import artifacts as art


def measured_root(run_dir: Path) -> Optional[Path]:
    run_dir = Path(run_dir)
    for rel in ("02_measured_data", "experimental_data"):
        p = art._open_dir(run_dir / rel)
        if p is not None:
            return p
    return None


def load_measured_catalog(run_dir: Path) -> Optional[Dict[str, Any]]:
    root = measured_root(run_dir)
    if root is None:
        return None
    for rel in ("00_index/catalog.json", "catalog.json"):
        obj = art._safe_json(root / rel)
        if obj is not None:
            return obj
    return None


def _classify_plot_family(name: str) -> str:
    n = name.lower()
    if n.startswith("06_") or n.startswith("summary"):
        return "summary"
    if n.startswith("07_") or "pulse_schedule" in n:
        return "pulse_schedule"
    if n.startswith("08_") or "spectrometer" in n or "dalpha" in n:
        return "spectrometer"
    if n.startswith("09_") or "soft_x" in n:
        return "soft_x_rays"
    if n.startswith("10_") or "thomson" in n:
        return "thomson"
    if n.startswith("11_") or "charge_exchange" in n or "cxrs" in n:
        return "cxrs"
    if n.startswith("12_") or "gas_injection" in n:
        return "gas"
    if n.startswith("13_") or "equilibrium_l2" in n:
        return "equilibrium_l2"
    if n.startswith("01_") or ("plasma" in n and "i_plasma" not in n):
        return "plasma"
    if n.startswith("02_") or "pf_" in n or "current" in n:
        return "pf"
    if n.startswith("03_") or "flux" in n or "pickup" in n or "audit" in n:
        return "magnetics"
    if n.startswith("04_") or "machine" in n or "limiter" in n:
        return "geometry"
    return "other"


def measured_plots_grouped(run_dir: Path) -> Dict[str, List[Path]]:
    grouped: Dict[str, List[Path]] = {
        "plasma": [],
        "pf": [],
        "magnetics": [],
        "geometry": [],
        "summary": [],
        "pulse_schedule": [],
        "spectrometer": [],
        "soft_x_rays": [],
        "thomson": [],
        "cxrs": [],
        "gas": [],
        "equilibrium_l2": [],
        "other": [],
    }
    for p in art.measured_plot_paths(run_dir):
        grouped[_classify_plot_family(p.name)].append(p)
    return {k: v for k, v in grouped.items() if v}


def _csv_section(rel: str) -> str:
    r = rel.replace("\\", "/").lower()
    if "/01_plasma/" in r:
        return "plasma"
    if "/02_pf/" in r:
        return "pf"
    if "/03_magnetics/" in r:
        return "magnetics"
    if "/04_geometry/" in r:
        return "geometry"
    if "/06_summary/" in r:
        return "summary"
    if "/07_pulse_schedule/" in r:
        return "pulse_schedule"
    if "/08_spectrometer" in r:
        return "spectrometer"
    if "/09_soft_x_rays/" in r:
        return "soft_x_rays"
    if "/10_thomson" in r:
        return "thomson"
    if "/11_charge_exchange/" in r:
        return "cxrs"
    if "/12_gas_injection/" in r:
        return "gas"
    if "/13_equilibrium" in r:
        return "equilibrium_l2"
    if "/l1/" in r:
        return "l1"
    if "/l3/" in r:
        return "l3"
    return "other"


def measured_csv_inventory(run_dir: Path, *, disk_walk: bool = True) -> List[Dict[str, Any]]:
    """Inventory Level-2 CSVs. Prefer catalog paths; optional shallow disk walk."""
    root = measured_root(run_dir)
    if root is None:
        return []
    run_dir = Path(run_dir)
    catalog = load_measured_catalog(run_dir) or {}
    families = catalog.get("families") if isinstance(catalog.get("families"), dict) else {}
    items: List[Dict[str, Any]] = []
    seen: set[str] = set()

    def _add(path: Path, family: str) -> None:
        try:
            if not path.is_file() or path.suffix.lower() != ".csv":
                return
        except OSError:
            return
        rel = art.rel_posix(path, run_dir)
        if rel in seen or rel.startswith("..") or art.safe_resolve_under(run_dir, rel) is None:
            return
        seen.add(rel)
        meta = families.get(family) if isinstance(families.get(family), dict) else {}
        try:
            nbytes = path.stat().st_size
        except OSError:
            nbytes = 0
        items.append(
            {
                "family": family,
                "rel": rel,
                "name": path.name,
                "bytes": nbytes,
                "columns": meta.get("columns") if isinstance(meta, dict) else None,
                "n_rows_approx": meta.get("n_rows_approx") if isinstance(meta, dict) else None,
                "section": _csv_section(rel),
            }
        )

    if isinstance(families, dict):
        for fam, meta in families.items():
            if not isinstance(meta, dict):
                continue
            rel = meta.get("path")
            if isinstance(rel, str) and rel.lower().endswith(".csv"):
                p = run_dir / rel.replace("\\", "/")
                if not p.is_file():
                    p = root / Path(rel).name
                _add(p, str(fam))

    # Catalog is enough for the happy path — skip deep walks unless asked.
    if disk_walk and not items:
        for sub in ("01_plasma", "02_pf", "03_magnetics", "04_geometry"):
            opened = art._open_dir(root / sub)
            if opened is None:
                continue
            try:
                for dirpath, dirnames, filenames in os.walk(opened, topdown=True, followlinks=False):
                    base = Path(dirpath)
                    depth = len(base.parts) - len(opened.parts)
                    if depth > 1:
                        dirnames[:] = []
                    dirnames[:] = [n for n in dirnames if not art._is_reparse_point(base / n)]
                    for name in filenames:
                        if name.lower().endswith(".csv"):
                            _add(base / name, Path(name).stem)
            except OSError:
                continue
    elif disk_walk:
        # Optional diagnostic folders only (core paths already come from catalog).
        for sub in (
            "06_summary",
            "07_pulse_schedule",
            "08_spectrometer_visible",
            "09_soft_x_rays",
            "10_thomson_scattering",
            "11_charge_exchange",
            "12_gas_injection",
            "13_equilibrium",
        ):
            opened = art._open_dir(root / sub)
            if opened is None:
                continue
            try:
                for p in opened.glob("*.csv"):
                    _add(p, p.stem)
                for p in opened.glob("*/*.csv"):
                    _add(p, p.stem)
            except OSError:
                continue

    items.sort(key=lambda x: (str(x.get("section") or ""), str(x.get("rel") or "")))
    return items


def csv_preview_rows(path: Path, *, max_rows: int = 8, max_bytes: int = 1_500_000) -> Optional[List[Dict[str, Any]]]:
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size > max_bytes:
            return None
    except OSError:
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            rows: List[Dict[str, Any]] = []
            fields = list(reader.fieldnames or [])[:12]
            for i, row in enumerate(reader):
                if i >= max_rows:
                    break
                rows.append({k: row.get(k) for k in fields})
            return rows
    except Exception:
        return None


def level2_status_files(run_dir: Path) -> Dict[str, Optional[Dict[str, Any]]]:
    root = measured_root(run_dir)
    if root is None:
        return {"l1": None, "l3": None, "optional": None}
    return {
        "l1": art._safe_json(root / "l1" / "STATUS.json"),
        "l3": art._safe_json(root / "l3" / "STATUS.json"),
        "optional": art._safe_json(root / "00_index" / "optional_diagnostics.json"),
    }


def shot_cache_status(
    cache_root: Path,
    shot: int,
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> Dict[str, Any]:
    from mast_freegsnke.download import group_cache_hit

    shot_dir = Path(cache_root) / f"shot_{int(shot)}"

    def _hit(group: str) -> bool:
        try:
            return group_cache_hit(shot_dir, group)
        except OSError:
            return False

    req = list(required)
    opt = list(optional)
    req_hits = [g for g in req if _hit(g)] if shot_dir.is_dir() else []
    opt_hits = [g for g in opt if _hit(g)] if shot_dir.is_dir() else []
    missing = [g for g in req if g not in req_hits]
    return {
        "shot": int(shot),
        "cache_dir": str(shot_dir),
        "required_hits": req_hits,
        "optional_hits": opt_hits,
        "missing_required": missing,
        "ready": bool(req) and not missing,
        "partial": 0 < len(req_hits) < len(req),
    }
