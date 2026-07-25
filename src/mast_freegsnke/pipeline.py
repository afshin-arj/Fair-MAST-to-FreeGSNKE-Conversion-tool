
from __future__ import annotations

import json
import os
import platform
import shutil
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import AppConfig, cache_dir_for_shot, run_dir_for_shot
from .download import (
    BulkDownloader,
    build_cache_report,
    check_groups_respecting_cache,
    group_cache_reusable,
)
from .extract import Extractor
from .generate import ScriptGenerator
from .mastapp import MastAppClient
from .util import ensure_dir, write_json
from .windowing import TimeWindow, infer_time_window
from .window_quality import WindowDiagnostics, evaluate_time_window, format_diagnostics
from .window_consensus import ConsensusWindow, infer_consensus_window
from .probe_geometry import build_geometry_from_machine_dir, write_geometry_json, write_geometry_pickle, write_geometry_pickle_internal
from .machine_authority import machine_authority_from_dir, snapshot_machine_authority
from .provenance import write_provenance, write_manifest_v2
from .freegsnke_runner import FreeGSNKERunner, evolutive_partial_history_n, write_execution_report
from .diagnostic_contracts import (
    load_contracts,
    resolve_contracts_for_run,
    validate_contracts,
    write_resolved_contracts,
)
from .diagnostic_calibration import (
    CalibrationError,
    apply_diagnostic_calibration,
    calibration_status_line,
    load_diagnostic_calibration,
    merge_calibration_contracts,
    snapshot_diagnostic_calibration,
)
from .coil_map import apply_coil_map, load_coil_map, validate_coil_map, write_resolved_coil_map
from .voltage_map import (
    apply_voltage_map,
    load_voltage_map,
    snapshot_voltage_map_hash,
    validate_voltage_map,
)
from .evolutive_authority import load_evolutive_authority, write_evolutive_authority
from .shot_summary import write_shot_expert_overlay
from .experimental_data import build_experimental_data
from .synthetic_extract import extract_synthetic_by_contracts
from .metrics import compare_from_contracts
from .execution_authority import write_execution_authority
from .equilibrium_presentation import PresentationAuthority, write_presentation_authority


def _resolve_config_path(raw: Optional[str], repo_root: Path) -> Optional[Path]:
    if not raw:
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (repo_root / p).resolve()
    return p


# Compatibility junctions created by shot_layout (redirects, not primary content).
_LAYOUT_SHIM_NAMES = frozenset(
    {
        "contracts",
        "metrics",
        "provenance",
        "machine_authority_snapshot",
        "experimental_data",
        "synthetic",
        "presentation",
        "evolutive",
        "downstream",
    }
)


def _is_windows_reparse_point(path: Path) -> bool:
    """True for Windows junctions/symlinks (layout shims)."""
    if os.name != "nt":
        return path.is_symlink()
    try:
        if path.is_symlink():
            return True
        st = path.lstat()
        return bool(getattr(st, "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def _remove_layout_shim(path: Path) -> None:
    """Remove a junction/symlink shim without deleting its target content."""
    try:
        path.unlink()
    except OSError:
        # Directory junction fallback
        try:
            path.rmdir()
        except OSError:
            pass


def _strip_reparse_points(root: Path, *, max_depth: int = 3) -> int:
    """Remove junction/symlink shims under ``root`` (shallow). Returns count removed.

    Archived Windows junctions keep *absolute* targets into the live SHOT tree.
    After a re-run moves ``06_authorities/``, those history junctions break and
    directory walks raise ``FileNotFoundError``. Drop the reparse points; the
    real content already lives under numbered folders in the same archive.
    """
    if not root.is_dir() or _is_windows_reparse_point(root):
        return 0
    removed = 0
    # Top-down by depth so we only scan a few levels (history/<ts>/…).
    stack: List[Tuple[Path, int]] = [(root, 0)]
    while stack:
        cur, depth = stack.pop()
        try:
            children = list(cur.iterdir())
        except OSError:
            continue
        for child in children:
            if _is_windows_reparse_point(child):
                _remove_layout_shim(child)
                removed += 1
                continue
            if depth < max_depth and child.is_dir():
                stack.append((child, depth + 1))
    return removed


def _sanitize_history_reparse_points(run_dir: Path) -> int:
    """Strip dangling layout junctions from all ``history/<ts>/`` archives."""
    hist = Path(run_dir) / "history"
    if not hist.is_dir():
        return 0
    total = 0
    try:
        entries = list(hist.iterdir())
    except OSError:
        return 0
    for entry in entries:
        if entry.is_dir() and not _is_windows_reparse_point(entry):
            total += _strip_reparse_points(entry, max_depth=2)
    return total


def _robust_move(src: Path, dst: Path) -> None:
    """Move with Windows-friendly retries (AV / explorer locks)."""
    last: Optional[BaseException] = None
    for attempt in range(6):
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return
        except PermissionError as e:
            last = e
            time.sleep(0.15 * (attempt + 1))
        except OSError as e:
            last = e
            time.sleep(0.15 * (attempt + 1))
    # Last resort: copytree then remove (handles stubborn directory locks).
    try:
        if src.is_dir() and not _is_windows_reparse_point(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            shutil.rmtree(src, ignore_errors=True)
            if not src.exists():
                return
    except OSError as e:
        last = e
    raise PermissionError(f"Could not archive {src} -> {dst}: {last}") from last


def _archive_prior_run(run_dir: Path) -> Optional[str]:
    """Archive a previous run of the same shot into <run_dir>/history/<ts>/.

    Reruns must not mix stale artifacts (old logs, pickles, metrics,
    EXCEPTION_TRACEBACK.txt) with fresh outputs: the top level of the run
    folder is always a single clean, auditable run. Prior runs are preserved,
    never deleted.

    Layout junctions (``contracts`` → ``06_authorities/contracts``, etc.) are
    removed rather than archived — the real trees are moved via their numbered
    destinations. Archiving junctions previously left broken reparse points that
    made ``provenance_lock`` fail with PermissionError / FileNotFoundError on Windows.

    Returns the history subpath (relative to run_dir) if archiving happened.
    """
    run_dir = Path(run_dir)
    # Always scrub old archives first — absolute-target junctions go stale on re-run.
    _sanitize_history_reparse_points(run_dir)

    if not (run_dir / "manifest.json").exists():
        return None
    ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
    hist = run_dir / "history" / ts
    n = 0
    while hist.exists():
        n += 1
        hist = run_dir / "history" / f"{ts}_{n}"
    hist.mkdir(parents=True)
    # Drop every reparse shim; move only real trees / files.
    children = sorted(run_dir.iterdir(), key=lambda p: p.name)
    for child in children:
        if child.name == "history":
            continue
        if _is_windows_reparse_point(child):
            _remove_layout_shim(child)
            continue
        if child.name in _LAYOUT_SHIM_NAMES and child.is_dir():
            # Pointer folder with only MOVED.txt — archive the stub.
            try:
                marker = child / "MOVED.txt"
                n_entries = sum(1 for _ in child.iterdir())
            except OSError:
                marker = None
                n_entries = 0
            if marker is not None and marker.is_file() and n_entries <= 2:
                _robust_move(child, hist / child.name)
                continue
        _robust_move(child, hist / child.name)
    # Belt-and-suspenders: never leave reparse points inside the new archive.
    _strip_reparse_points(hist, max_depth=2)
    return str(hist.relative_to(run_dir))


@dataclass
class ShotPipeline:
    cfg: AppConfig
    templates_dir: Path

    def run(
        self,
        shot: int,
        machine_dir: Path,
        tstart: Optional[float] = None,
        tend: Optional[float] = None,
    ) -> Path:
        """Run the end-to-end deterministic pipeline.

        Parameters
        ----------
        shot:
            MAST shot number.
        machine_dir:
            Directory containing any machine-specific assets (including probe_geometry.json).
        tstart, tend:
            Optional deterministic override of the time window [s]. If provided, dominates consensus/inference.

        Returns
        -------
        run_dir:
            The created run directory path. A manifest is always written.
        """
        created_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        stage_log: List[Dict[str, Any]] = []
        blocking_errors: List[str] = []
        status = "started"

        ensure_dir(self.cfg.runs_dir)
        # User-facing layout: SHOT/<shot> (e.g. SHOT/30201); legacy SHOTS/ still supported if configured.
        run_dir = ensure_dir(run_dir_for_shot(self.cfg, shot))
        prior_run_archived_to = _archive_prior_run(run_dir)
        inputs_dir = ensure_dir(run_dir / "inputs")

        from .progress import write_run_progress

        def _flush_progress(current_stage: Optional[str] = None) -> None:
            # Progress is a UI sidecar — never let reader locks (WinError 5/32) abort
            # a real stage (false voltage_map_failed / similar).
            try:
                write_run_progress(
                    run_dir,
                    shot=int(shot),
                    status=status,
                    stage_log=stage_log,
                    blocking_errors=blocking_errors,
                    current_stage=current_stage,
                )
            except OSError:
                pass

        def _stage(name: str, ok: bool, **kw: Any) -> None:
            stage_log.append({"stage": name, "ok": bool(ok), **kw})
            _flush_progress(current_stage=name)

        _flush_progress(current_stage=None)

        if prior_run_archived_to is not None:
            _stage("prior_run_archived", True, dest=prior_run_archived_to)

        repo_root = self.templates_dir.parent

        # Machine authority (optional but strongly recommended for reviewer-grade runs).
        # If present, it is validated and snapshotted into the run directory.
        machine_snapshot = None
        ma_root = None
        calibration_snapshot = None
        calibration_apply = None
        if self.cfg.machine_authority_dir:
            ma_root = Path(self.cfg.machine_authority_dir)
            if not ma_root.is_absolute():
                ma_root = (repo_root / ma_root).resolve()
        else:
            default_ma = repo_root / "machine_authority"
            if default_ma.exists():
                ma_root = default_ma.resolve()

        if ma_root is not None and ma_root.exists():
            ma, ma_report = machine_authority_from_dir(ma_root)
            write_json(run_dir / "machine_authority_report.json", ma_report)
            if ma is not None:
                machine_snapshot = snapshot_machine_authority(ma, run_dir)
                _stage(
                    "machine_authority",
                    True,
                    root=str(ma_root),
                    authority=machine_snapshot.get("authority_name"),
                    version=machine_snapshot.get("authority_version"),
                )
            else:
                _stage("machine_authority", False, root=str(ma_root), errors=ma_report.get("errors"))
                if self.cfg.require_machine_authority:
                    blocking_errors.append("machine_authority_missing_or_invalid (see machine_authority_report.json)")
        else:
            note = "not_provided"
            if self.cfg.machine_authority_dir:
                note = f"machine_authority_dir_not_found:{self.cfg.machine_authority_dir}"
            _stage("machine_authority", False, note=note)
            if self.cfg.require_machine_authority:
                blocking_errors.append("machine_authority_required_but_missing")



        def _write_manifest(extra: Dict[str, Any]) -> None:
            manifest = {
                "shot": int(shot),
                "created_utc": created_utc,
                "status": status,
                "blocking_errors": blocking_errors,
                "stage_log": stage_log,
                "platform": {"python": platform.python_version(), "system": platform.platform()},
                "mastapp_base_url": self.cfg.mastapp_base_url,
                "required_groups": list(self.cfg.required_groups),
                "optional_groups": list(self.cfg.optional_groups),
                "level2_s3_prefix": self.cfg.level2_s3_prefix,
                "s3_layout_patterns": list(self.cfg.s3_layout_patterns),
                "s3_endpoint_url": self.cfg.s3_endpoint_url,
                "s3_no_sign_request": bool(self.cfg.s3_no_sign_request),
                "s5cmd_timeout_s": int(self.cfg.s5cmd_timeout_s),
                "cache_root": str(self.cfg.cache_dir),
                "machine_dir": str(machine_dir),
                "formed_plasma_frac": float(self.cfg.formed_plasma_frac),
                "prior_run_archived_to": prior_run_archived_to,
            }
            manifest.update(extra)
            write_json(run_dir / "manifest.json", manifest)
            _flush_progress(
                current_stage=stage_log[-1]["stage"] if stage_log else None
            )

        cache_root = ensure_dir(self.cfg.cache_dir)
        shot_cache: Optional[Path] = None
        extract_meta: Dict[str, Any] = {}
        exec_summary: Dict[str, Any] = {}
        metrics_summary: Any = None
        contracts_report: Any = None
        download_report: Dict[str, Any] = {}

        # Always attempt to write a manifest, even on failure.
        try:
            status = "running"
            _flush_progress(current_stage=stage_log[-1]["stage"] if stage_log else None)
            shot_cache_candidate = cache_dir_for_shot(self.cfg, shot)
            all_groups_cached = bool(self.cfg.allow_cache_reuse) and all(
                group_cache_reusable(shot_cache_candidate, g, shot=int(shot))
                for g in self.cfg.required_groups
            )

            if all_groups_cached:
                # Every required group is already cached: skip all network stages
                # (MastApp REST, S3 preflight, availability, sync) deterministically.
                shot_cache = shot_cache_candidate
                download_report = build_cache_report(shot_cache, self.cfg.required_groups)
                write_json(shot_cache / "download_report.json", download_report)
                _stage("mastapp_shot_exists", True, note="skipped_all_groups_cached")
                _stage("s3_shot_preflight", True, note="skipped_all_groups_cached")
                _stage("availability_check", True, note="skipped_all_groups_cached")
                _stage(
                    "download_groups",
                    True,
                    shot_cache=str(shot_cache),
                    cache_hits=sorted(download_report.keys()),
                    synced=[],
                    note="local_cache_only_no_s3_sync",
                    download_report=download_report,
                )
                # Optional audit groups: skip network entirely when all are cached.
                if self.cfg.optional_groups:
                    opt = list(self.cfg.optional_groups)
                    if all(group_cache_reusable(shot_cache, g, shot=int(shot)) for g in opt):
                        opt_rep = build_cache_report(shot_cache, opt)
                        for g in opt_rep:
                            opt_rep[g]["optional"] = True
                            opt_rep[g]["ok"] = True
                        download_report.update(opt_rep)
                        write_json(shot_cache / "download_report.json", download_report)
                        _stage(
                            "download_optional_groups",
                            True,
                            note="skipped_all_optional_cached",
                            cache_hits=sorted(opt),
                            optional_report=opt_rep,
                        )
                    else:
                        dl_opt = BulkDownloader(
                            s5cmd_path=self.cfg.s5cmd_path,
                            level2_s3_prefix=self.cfg.level2_s3_prefix,
                            layout_patterns=self.cfg.s3_layout_patterns,
                            s3_endpoint_url=self.cfg.s3_endpoint_url,
                            s3_no_sign_request=self.cfg.s3_no_sign_request,
                            timeout_s=self.cfg.s5cmd_timeout_s,
                        )
                        opt_rep = dl_opt.download_optional_groups(
                            shot,
                            opt,
                            shot_cache,
                            allow_cache_reuse=bool(self.cfg.allow_cache_reuse),
                        )
                        download_report.update(opt_rep)
                        _stage(
                            "download_optional_groups",
                            True,
                            optional_report=opt_rep,
                            cache_hits=sorted(g for g, r in opt_rep.items() if r.get("cache_hit")),
                            synced=sorted(g for g, r in opt_rep.items() if not r.get("cache_hit")),
                        )
            else:
                client = MastAppClient(base_url=self.cfg.mastapp_base_url)
                if not client.shot_exists(shot):
                    raise RuntimeError(f"Shot {shot} not available via MastApp REST at {self.cfg.mastapp_base_url}")
                _stage("mastapp_shot_exists", True)

                dl = BulkDownloader(
                    s5cmd_path=self.cfg.s5cmd_path,
                    level2_s3_prefix=self.cfg.level2_s3_prefix,
                    layout_patterns=self.cfg.s3_layout_patterns,
                    s3_endpoint_url=self.cfg.s3_endpoint_url,
                    s3_no_sign_request=self.cfg.s3_no_sign_request,
                    timeout_s=self.cfg.s5cmd_timeout_s,
                )

                # Transport preflight (v10.0.7): prevent indefinite hangs / wrong endpoints
                dl.preflight(shot)
                _stage("s3_shot_preflight", True, endpoint=self.cfg.s3_endpoint_url, no_sign=bool(self.cfg.s3_no_sign_request), timeout_s=int(self.cfg.s5cmd_timeout_s))

                # Pre-check group availability — skip S3 ls for groups already in local cache.
                avail = check_groups_respecting_cache(
                    shot=shot,
                    groups=self.cfg.required_groups,
                    discover=dl.discover_group_path,
                    shot_cache=shot_cache_candidate,
                    allow_cache_reuse=bool(self.cfg.allow_cache_reuse),
                )
                write_json(shot_cache_candidate / "availability.json", {k: v.__dict__ for k, v in avail.items()})
                missing = [k for k, v in avail.items() if not v.exists]
                if missing:
                    raise RuntimeError("Required Level-2 groups missing for shot {}: {}".format(shot, ", ".join(missing)))
                cached_avail = [
                    k
                    for k, v in avail.items()
                    if v.exists and isinstance(v.s3_path, str) and str(v.s3_path).startswith("local-cache:")
                ]
                _stage(
                    "availability_check",
                    True,
                    groups_ok=list(avail.keys()),
                    cache_hits=sorted(cached_avail),
                )

                # Download only missing groups (cache hits are not re-synced).
                shot_cache, download_report = dl.download_groups(
                    shot,
                    self.cfg.required_groups,
                    cache_root,
                    allow_cache_reuse=bool(self.cfg.allow_cache_reuse),
                )
                _stage(
                    "download_groups",
                    True,
                    shot_cache=str(shot_cache),
                    cache_hits=sorted(g for g, r in download_report.items() if r.get("cache_hit")),
                    synced=sorted(g for g, r in download_report.items() if not r.get("cache_hit")),
                    download_report=download_report,
                )
                if self.cfg.optional_groups:
                    opt_rep = dl.download_optional_groups(
                        shot,
                        list(self.cfg.optional_groups),
                        shot_cache,
                        allow_cache_reuse=bool(self.cfg.allow_cache_reuse),
                    )
                    download_report.update(opt_rep)
                    _stage(
                        "download_optional_groups",
                        True,
                        optional_report=opt_rep,
                        cache_hits=sorted(g for g, r in opt_rep.items() if r.get("cache_hit")),
                        synced=sorted(g for g, r in opt_rep.items() if not r.get("cache_hit")),
                    )

            # Rebuild classic MAST pickles when wall/pf_active fingerprints disagree.
            if (
                self.cfg.rebuild_machine_authority
                and ma_root is not None
                and ma_root.exists()
                and shot_cache is not None
            ):
                from .machine_sync import maybe_rebuild_classic_machine

                rebuild_rep = maybe_rebuild_classic_machine(
                    shot_cache,
                    ma_root,
                    shot=int(shot),
                    force=False,
                    archive_mastu=False,
                )
                write_json(run_dir / "machine_rebuild_report.json", rebuild_rep)
                _stage(
                    "machine_rebuild",
                    bool(rebuild_rep.get("ok")),
                    rebuilt=bool(rebuild_rep.get("rebuilt")),
                    reason=(rebuild_rep.get("check") or {}).get("reason"),
                    error=rebuild_rep.get("error"),
                )
                if rebuild_rep.get("rebuilt") and rebuild_rep.get("ok"):
                    ma, ma_report = machine_authority_from_dir(ma_root)
                    write_json(run_dir / "machine_authority_report.json", ma_report)
                    if ma is not None:
                        machine_snapshot = snapshot_machine_authority(ma, run_dir)
                elif not rebuild_rep.get("ok") and self.cfg.require_machine_authority:
                    blocking_errors.append(
                        f"machine_rebuild_failed: {rebuild_rep.get('error') or rebuild_rep.get('check')}"
                    )

            # Extract CSV inputs (optional stack)
            try:
                ex = Extractor(formed_plasma_frac=self.cfg.formed_plasma_frac)
                extract_meta = ex.extract(shot_cache, inputs_dir)
                _stage("extract_csv", True, meta=extract_meta)
            except Exception as e:
                extract_meta = {"extract_error": str(e)}
                _stage("extract_csv", False, error=str(e))
                blocking_errors.append(f"extract_csv_failed: {e}")
            write_json(inputs_dir / "extract_meta.json", extract_meta)

            # Optional diagnostic calibration (mirnov/saddle/omaha) — fail-closed, never invents
            cal_path = _resolve_config_path(self.cfg.diagnostic_calibration_path, repo_root)
            if cal_path is not None:
                try:
                    cal = load_diagnostic_calibration(cal_path)
                    calibration_snapshot = snapshot_diagnostic_calibration(cal, run_dir)
                    # extract_meta must exist before apply (units gate)
                    calibration_apply = apply_diagnostic_calibration(inputs_dir, cal)
                    if not calibration_apply.get("ok", False):
                        blocking_errors.append(
                            "diagnostic_calibration_apply_failed: "
                            + "; ".join(calibration_apply.get("errors", []))
                        )
                        _stage(
                            "diagnostic_calibration",
                            False,
                            errors=calibration_apply.get("errors"),
                            status=cal.status,
                        )
                    else:
                        _stage(
                            "diagnostic_calibration",
                            True,
                            status=cal.status,
                            n_calibrated=cal.n_calibrated,
                            n_applied=len(calibration_apply.get("applied") or []),
                            n_synthesizable=cal.n_synthesizable,
                            banner=calibration_status_line(
                                path=self.cfg.diagnostic_calibration_path,
                                cal=cal,
                                apply_report=calibration_apply,
                            ),
                        )
                except CalibrationError as e:
                    blocking_errors.append(f"diagnostic_calibration_invalid: {e}")
                    _stage("diagnostic_calibration", False, error=str(e))
                except Exception as e:
                    blocking_errors.append(f"diagnostic_calibration_failed: {type(e).__name__}: {e}")
                    _stage("diagnostic_calibration", False, error=str(e))
            else:
                _stage(
                    "diagnostic_calibration",
                    True,
                    note="no_diagnostic_calibration_path",
                    banner=calibration_status_line(path=None),
                )

            # Coil-map authority → pf_currents.csv (binding; after extract, before execute)
            raw_pf = inputs_dir / "pf_active_raw.csv"
            cm_path = _resolve_config_path(self.cfg.coil_map_path, repo_root)
            if cm_path is not None:
                try:
                    coil_map = load_coil_map(cm_path)
                    cm_report = validate_coil_map(coil_map)
                    write_resolved_coil_map(run_dir, coil_map)
                    if not cm_report.get("ok", False):
                        blocking_errors.append("coil_map_invalid: " + "; ".join(cm_report.get("errors", [])))
                        _stage("coil_map", False, n=cm_report.get("n"), errors=cm_report.get("errors"))
                    else:
                        apply_rep = apply_coil_map(raw_pf, inputs_dir / "pf_currents.csv", coil_map)
                        write_json(inputs_dir / "coil_map_apply_report.json", apply_rep)
                        if not apply_rep.get("ok", False):
                            blocking_errors.append(
                                "coil_map_apply_failed: " + "; ".join(apply_rep.get("errors", []))
                            )
                            _stage("coil_map_apply", False, errors=apply_rep.get("errors"))
                        else:
                            _stage("coil_map_apply", True, n_mapped=apply_rep.get("n_mapped"), coils=apply_rep.get("coils"))
                except Exception as e:
                    blocking_errors.append(f"coil_map_failed: {type(e).__name__}: {e}")
                    _stage("coil_map", False, error=str(e))
            else:
                if self.cfg.execute_freegsnke and raw_pf.exists():
                    blocking_errors.append(
                        "coil_map_required_for_execution: set coil_map_path in config "
                        "(heuristic PF mapping is not allowed in the happy path)"
                    )
                    _stage("coil_map", False, note="missing_coil_map_path")
                else:
                    _stage("coil_map", True, note="no_coil_map_path")

            # Voltage-map authority → pf_voltages.csv (binding for evolutive)
            raw_v = inputs_dir / "pf_voltages_raw.csv"
            vm_path = _resolve_config_path(self.cfg.voltage_map_path, repo_root)
            if vm_path is not None:
                try:
                    vmap = load_voltage_map(vm_path)
                    vm_report = validate_voltage_map(vmap)
                    snapshot_voltage_map_hash(vmap, run_dir)
                    if not vm_report.get("ok", False):
                        blocking_errors.append(
                            "voltage_map_invalid: " + "; ".join(vm_report.get("errors", []))
                        )
                        _stage("voltage_map", False, errors=vm_report.get("errors"))
                    elif not raw_v.exists():
                        if self.cfg.execute_evolutive:
                            blocking_errors.append(
                                "voltage_map_apply_failed: missing inputs/pf_voltages_raw.csv "
                                "(FAIR-MAST coil_voltage not extracted; cannot run evolutive)"
                            )
                            _stage("voltage_map_apply", False, note="missing_pf_voltages_raw")
                        else:
                            _stage("voltage_map", True, note="map_ok_but_no_raw_voltages")
                    else:
                        v_apply = apply_voltage_map(
                            raw_v,
                            inputs_dir / "pf_voltages.csv",
                            vmap,
                            pf_currents_csv=inputs_dir / "pf_currents.csv",
                        )
                        write_json(inputs_dir / "voltage_map_apply_report.json", v_apply)
                        if not v_apply.get("ok", False):
                            blocking_errors.append(
                                "voltage_map_apply_failed: " + "; ".join(v_apply.get("errors", []))
                            )
                            _stage("voltage_map_apply", False, errors=v_apply.get("errors"))
                        else:
                            _stage(
                                "voltage_map_apply",
                                True,
                                n_mapped=v_apply.get("n_mapped"),
                                n_default_zero=v_apply.get("n_default_zero"),
                                n_ohmic=v_apply.get("n_ohmic"),
                                n_ohmic_deferred=v_apply.get("n_ohmic_deferred"),
                                drive=v_apply.get("drive_summary", {}).get("line"),
                            )
                except Exception as e:
                    blocking_errors.append(f"voltage_map_failed: {type(e).__name__}: {e}")
                    _stage("voltage_map", False, error=str(e))
            else:
                if self.cfg.execute_evolutive:
                    blocking_errors.append(
                        "voltage_map_required_for_evolutive: set voltage_map_path in config"
                    )
                    _stage("voltage_map", False, note="missing_voltage_map_path")
                else:
                    _stage("voltage_map", True, note="no_voltage_map_path")

            # Generate run scripts/stubs
            gen = ScriptGenerator(templates_dir=self.templates_dir)
            gen.generate(run_dir=run_dir, machine_dir=machine_dir, formed_frac=self.cfg.formed_plasma_frac)
            _stage("generate_scripts", True)

            # Execution-state authority (v9): eliminate hidden defaults in generated scripts
            # by exporting an explicit authority bundle under inputs/execution_authority/.
            try:
                ea_root = write_execution_authority(inputs_dir, metrics_n_times=int(self.cfg.metrics_n_times))
                _stage("execution_authority", True, root=str(ea_root), metrics_n_times=int(self.cfg.metrics_n_times))
            except Exception as e:
                _stage("execution_authority", False, error=str(e))
                blocking_errors.append(f"execution_authority_write_failed:{e}")

            try:
                pres = PresentationAuthority(
                    write_equilibrium_gifs=bool(self.cfg.write_equilibrium_gifs),
                    write_eq_frames=bool(self.cfg.write_eq_frames),
                    gif_fps=float(self.cfg.equilibrium_gif_fps),
                    gif_dpi=int(self.cfg.equilibrium_gif_dpi),
                )
                pres_path = write_presentation_authority(inputs_dir, pres)
                _stage(
                    "presentation_authority",
                    True,
                    path=str(pres_path),
                    write_equilibrium_gifs=bool(pres.write_equilibrium_gifs),
                    gif_fps=float(pres.gif_fps),
                )
            except Exception as e:
                _stage("presentation_authority", False, error=str(e))
                blocking_errors.append(f"presentation_authority_write_failed:{e}")

            # Evolutive authority snapshot (fail-closed when execute_evolutive)
            if self.cfg.execute_evolutive:
                evo_path = _resolve_config_path(self.cfg.evolutive_authority_path, repo_root)
                if evo_path is None or not evo_path.exists():
                    blocking_errors.append(
                        "evolutive_authority_required: set evolutive_authority_path "
                        "(all nl_solver numerics must be declared; no hidden defaults)"
                    )
                    _stage("evolutive_authority", False, note="missing_path")
                else:
                    try:
                        evo_auth = load_evolutive_authority(evo_path)
                        evo_root = write_evolutive_authority(inputs_dir, evo_auth)
                        _stage("evolutive_authority", True, root=str(evo_root))
                    except Exception as e:
                        blocking_errors.append(f"evolutive_authority_failed: {type(e).__name__}: {e}")
                        _stage("evolutive_authority", False, error=str(e))
            else:
                _stage("evolutive_authority", True, note="execute_evolutive=false")

            # ADR-001 optional TORAX GEQDSK export authority (default off)
            if self.cfg.export_torax_geometry:
                from .torax_geometry_export import (
                    load_torax_geometry_export_authority,
                    write_torax_geometry_export_authority,
                )

                tg_path = _resolve_config_path(
                    self.cfg.torax_geometry_export_authority_path, repo_root
                )
                if tg_path is None or not tg_path.exists():
                    blocking_errors.append(
                        "torax_geometry_export_authority_required: set "
                        "torax_geometry_export_authority_path when export_torax_geometry=true "
                        "(ADR-001 fail-closed)"
                    )
                    _stage("torax_geometry_export_authority", False, note="missing_path")
                else:
                    try:
                        tg_auth = load_torax_geometry_export_authority(tg_path)
                        tg_out = write_torax_geometry_export_authority(inputs_dir, tg_auth)
                        _stage(
                            "torax_geometry_export_authority",
                            True,
                            path=str(tg_out),
                            rcentr_m=float(tg_auth.rcentr_m),
                            cocos_declared=str(tg_auth.cocos_declared),
                        )
                    except Exception as e:
                        blocking_errors.append(
                            f"torax_geometry_export_authority_failed: {type(e).__name__}: {e}"
                        )
                        _stage("torax_geometry_export_authority", False, error=str(e))
            else:
                _stage("torax_geometry_export_authority", True, note="export_torax_geometry=false")

            # ADR-002 optional FAIR-MAST EFIT++ compare authority
            if self.cfg.compare_efit_archive:
                from .efit_compare import load_efit_compare_authority, write_efit_compare_authority

                ec_path = _resolve_config_path(self.cfg.efit_compare_authority_path, repo_root)
                if ec_path is None or not ec_path.exists():
                    blocking_errors.append(
                        "efit_compare_authority_required: set efit_compare_authority_path "
                        "when compare_efit_archive=true (ADR-002 fail-closed)"
                    )
                    _stage("efit_compare_authority", False, note="missing_path")
                else:
                    try:
                        ec_auth = load_efit_compare_authority(ec_path)
                        ec_out = write_efit_compare_authority(inputs_dir, ec_auth)
                        _stage(
                            "efit_compare_authority",
                            True,
                            path=str(ec_out),
                            source=str(ec_auth.source),
                        )
                    except Exception as e:
                        blocking_errors.append(
                            f"efit_compare_authority_failed: {type(e).__name__}: {e}"
                        )
                        _stage("efit_compare_authority", False, error=str(e))
            else:
                _stage("efit_compare_authority", True, note="compare_efit_archive=false")

            # ADR-004 Phase 2: always snapshot planner/coil_limits/circuit_dynamics when paths set
            # (UI visibility); execute_planner=true additionally fail-closes on awaiting limits.
            from .coil_limits import CoilLimitsError, load_coil_limits, write_coil_limits
            from .circuit_dynamics_authority import (
                CircuitDynamicsAuthorityError,
                load_circuit_dynamics_authority,
                write_circuit_dynamics_authority,
            )
            from .planner import PlannerError, load_planner_authority, write_planner_authority

            pl_path = _resolve_config_path(self.cfg.planner_authority_path, repo_root)
            cl_path = _resolve_config_path(self.cfg.coil_limits_authority_path, repo_root)
            cd_path = _resolve_config_path(self.cfg.circuit_dynamics_authority_path, repo_root)
            if pl_path is not None and pl_path.exists():
                try:
                    pl_auth = load_planner_authority(pl_path)
                    pl_out = write_planner_authority(inputs_dir, pl_auth)
                    _stage(
                        "planner_authority",
                        True,
                        path=str(pl_out),
                        enabled=bool(pl_auth.enabled),
                        note=("execute_planner" if self.cfg.execute_planner else "snapshot_only"),
                    )
                except Exception as e:
                    if self.cfg.execute_planner:
                        blocking_errors.append(f"planner_authority_failed: {type(e).__name__}: {e}")
                        _stage("planner_authority", False, error=str(e))
                    else:
                        _stage("planner_authority", True, note=f"snapshot_failed:{e}")
            elif self.cfg.execute_planner:
                blocking_errors.append(
                    "planner_authority_required: set planner_authority_path when execute_planner=true"
                )
                _stage("planner_authority", False, note="missing_path")
            else:
                _stage("planner_authority", True, note="no_path")

            if cl_path is not None and cl_path.exists():
                try:
                    cl_auth = load_coil_limits(cl_path)
                    cl_out = write_coil_limits(inputs_dir, cl_auth)
                    if cl_auth.awaiting:
                        if self.cfg.execute_planner:
                            blocking_errors.append(
                                "coil_limits_awaiting_authority: populate cited Imax_A/Vmax_V "
                                "or measured_peak_margin policy before execute_planner "
                                "(never invent limits)"
                            )
                            _stage(
                                "coil_limits_authority",
                                False,
                                path=str(cl_out),
                                status=cl_auth.status,
                            )
                        else:
                            _stage(
                                "coil_limits_authority",
                                True,
                                path=str(cl_out),
                                status=cl_auth.status,
                                note="awaiting_ok_while_planner_off",
                            )
                    else:
                        _stage(
                            "coil_limits_authority",
                            True,
                            path=str(cl_out),
                            n_circuits=len(cl_auth.circuits),
                            limit_policy=cl_auth.limit_policy,
                            margin_factor=cl_auth.margin_factor,
                            citation=cl_auth.citation,
                        )
                except (CoilLimitsError, PlannerError, Exception) as e:
                    if self.cfg.execute_planner:
                        blocking_errors.append(f"coil_limits_authority_failed: {type(e).__name__}: {e}")
                        _stage("coil_limits_authority", False, error=str(e))
                    else:
                        _stage("coil_limits_authority", True, note=f"snapshot_failed:{e}")
            elif self.cfg.execute_planner:
                blocking_errors.append(
                    "coil_limits_authority_required: set coil_limits_authority_path "
                    "when execute_planner=true (ADR-004 hard gate)"
                )
                _stage("coil_limits_authority", False, note="missing_path")
            else:
                _stage("coil_limits_authority", True, note="no_path")

            if cd_path is not None and cd_path.exists():
                try:
                    cd_auth = load_circuit_dynamics_authority(cd_path)
                    cd_out = write_circuit_dynamics_authority(inputs_dir, cd_auth)
                    if cd_auth.awaiting and self.cfg.execute_planner:
                        blocking_errors.append(
                            "circuit_dynamics_awaiting_authority: cite PF R/L table "
                            "before execute_planner"
                        )
                        _stage("circuit_dynamics_authority", False, path=str(cd_out))
                    else:
                        _stage(
                            "circuit_dynamics_authority",
                            True,
                            path=str(cd_out),
                            n_circuits=len(cd_auth.circuits),
                            citation=cd_auth.citation,
                            note=("snapshot_only" if not self.cfg.execute_planner else "ready"),
                        )
                except (CircuitDynamicsAuthorityError, Exception) as e:
                    if self.cfg.execute_planner:
                        blocking_errors.append(
                            f"circuit_dynamics_authority_failed: {type(e).__name__}: {e}"
                        )
                        _stage("circuit_dynamics_authority", False, error=str(e))
                    else:
                        _stage("circuit_dynamics_authority", True, note=f"snapshot_failed:{e}")
            elif self.cfg.execute_planner:
                _stage("circuit_dynamics_authority", True, note="no_path_freegsnke_fallback")
            else:
                _stage("circuit_dynamics_authority", True, note="no_path")

            # Time window: override > consensus > single-signal inference
            window_override: Optional[Dict[str, Any]] = None
            if tstart is not None and tend is not None:
                if float(tend) <= float(tstart):
                    raise ValueError(f"Invalid override window: tend({tend}) must be > tstart({tstart})")
                window_override = {"t_start": float(tstart), "t_end": float(tend), "source": "override"}
                write_json(inputs_dir / "window_override.json", window_override)
                _stage("window_override", True, t_start=float(tstart), t_end=float(tend))
            elif (tstart is None) != (tend is None):
                raise ValueError("Window override requires both tstart and tend.")

            consensus_obj: Optional[ConsensusWindow] = None
            try:
                consensus_obj = infer_consensus_window(inputs_dir=inputs_dir, formed_frac=self.cfg.formed_plasma_frac)
                write_json(inputs_dir / "window_consensus.json", consensus_obj.__dict__)
                _stage("window_consensus", True, frac_agree=consensus_obj.frac_sources_agree, sources=consensus_obj.sources_used)
            except Exception as e:
                _stage("window_consensus", False, error=str(e))

            final_tw: Optional[TimeWindow] = None
            if window_override is not None:
                final_tw = TimeWindow(
                    t_start=float(window_override["t_start"]),
                    t_end=float(window_override["t_end"]),
                    source="override",
                    signal_column=None,
                    threshold=None,
                    note="deterministic_override_dominates_all",
                )
            elif consensus_obj is not None:
                final_tw = TimeWindow(
                    t_start=float(consensus_obj.t_start),
                    t_end=float(consensus_obj.t_end),
                    source=f"consensus:{consensus_obj.method}",
                    signal_column=None,
                    threshold=None,
                    note=f"frac_sources_agree={consensus_obj.frac_sources_agree}",
                )
            else:
                try:
                    final_tw = infer_time_window(inputs_dir=inputs_dir, formed_frac=self.cfg.formed_plasma_frac)
                except Exception as e:
                    blocking_errors.append(f"window_finalize_failed: {e}")
                    _stage("window_finalize", False, error=str(e))

            if final_tw is not None:
                write_json(inputs_dir / "window.json", final_tw.__dict__)
                _stage("window_finalize", True, t_start=final_tw.t_start, t_end=final_tw.t_end, source=final_tw.source)
                note = str(final_tw.note or "")
                if note.startswith("fallback_") and str(final_tw.source) != "override":
                    blocking_errors.append(
                        "window_fallback_blocked: "
                        f"{note} (source={final_tw.source}, col={final_tw.signal_column}). "
                        "Formed-plasma window must come from Ip/consensus or explicit --tstart/--tend — "
                        "refusing PF-proxy / full-extent silence."
                    )

            # ADR-004 Phase 1: EFIT++ → declared profile_trajectory (needs window.json)
            if self.cfg.build_profile_trajectory:
                from dataclasses import replace as _dc_replace

                from .efit_profile_fit import ProfileFitError, run_profile_trajectory_stage
                from .profile_trajectory import load_profile_trajectory_policy

                pt_path = _resolve_config_path(
                    self.cfg.profile_trajectory_authority_path, repo_root
                )
                if pt_path is None or not pt_path.exists():
                    blocking_errors.append(
                        "profile_trajectory_authority_required: set "
                        "profile_trajectory_authority_path when build_profile_trajectory=true "
                        "(ADR-004 fail-closed)"
                    )
                    _stage("profile_trajectory", False, note="missing_path")
                elif shot_cache is None:
                    try:
                        _pol0 = load_profile_trajectory_policy(pt_path)
                        _req0 = bool(_pol0.require)
                    except Exception:
                        _req0 = True
                    msg = "profile_trajectory skipped: no shot cache for equilibrium.zarr"
                    if _req0:
                        blocking_errors.append(msg)
                        _stage("profile_trajectory", False, note="no_cache")
                    else:
                        _stage("profile_trajectory", True, note="no_cache_soft_skip")
                elif final_tw is None:
                    try:
                        _pol0 = load_profile_trajectory_policy(pt_path)
                        _req0 = bool(_pol0.require)
                    except Exception:
                        _req0 = True
                    msg = "profile_trajectory skipped: window.json not finalized"
                    if _req0:
                        blocking_errors.append(msg)
                        _stage("profile_trajectory", False, note="no_window")
                    else:
                        _stage("profile_trajectory", True, note="no_window_soft_skip")
                else:
                    try:
                        policy = load_profile_trajectory_policy(pt_path)
                        policy = _dc_replace(policy, n_knots=int(self.cfg.metrics_n_times))
                        pt_rep = run_profile_trajectory_stage(
                            inputs_dir=inputs_dir,
                            cache_dir=shot_cache,
                            policy_path=pt_path,
                            shot=int(shot),
                            policy=policy,
                        )
                        if pt_rep.get("ok"):
                            _stage(
                                "profile_trajectory",
                                True,
                                status=pt_rep.get("status"),
                                fit_mode_used=pt_rep.get("fit_mode_used"),
                                n_knots=pt_rep.get("n_knots"),
                                content_sha256=pt_rep.get("content_sha256"),
                                path=pt_rep.get("path"),
                            )
                        elif policy.require:
                            blocking_errors.append(
                                "profile_trajectory_required: "
                                f"{pt_rep.get('status')}: {pt_rep.get('fix_hint')}"
                            )
                            _stage(
                                "profile_trajectory",
                                False,
                                status=pt_rep.get("status"),
                                fix_hint=pt_rep.get("fix_hint"),
                                provenance=pt_rep.get("provenance"),
                            )
                        else:
                            _stage(
                                "profile_trajectory",
                                True,
                                note=str(pt_rep.get("status") or "skipped"),
                                status=pt_rep.get("status"),
                                fix_hint=pt_rep.get("fix_hint"),
                                provenance=pt_rep.get("provenance"),
                            )
                    except ProfileFitError as e:
                        blocking_errors.append(
                            f"profile_trajectory_failed: {type(e).__name__}: {e}"
                        )
                        _stage("profile_trajectory", False, error=str(e))
                    except Exception as e:
                        blocking_errors.append(
                            f"profile_trajectory_failed: {type(e).__name__}: {e}"
                        )
                        _stage("profile_trajectory", False, error=str(e))
            else:
                _stage("profile_trajectory", True, note="build_profile_trajectory=false")

            # QC diagnostics (best-effort, but failures are blocking if window exists)
            window_diag: Optional[WindowDiagnostics] = None
            if final_tw is not None:
                try:
                    window_diag = evaluate_time_window(inputs_dir=inputs_dir, tw=final_tw)
                    write_json(inputs_dir / "window_diagnostics.json", window_diag.__dict__)
                    (inputs_dir / "WINDOW_QC_REPORT.txt").write_text(format_diagnostics(window_diag))
                    _stage("window_qc", True, confidence=window_diag.confidence, flags=window_diag.flags)
                except Exception as e:
                    blocking_errors.append(f"window_qc_failed: {e}")
                    _stage("window_qc", False, error=str(e))
            else:
                _stage("window_qc", False, note="skipped_no_window")

            # Probe geometry (required for synthetic diagnostics)
            geom, geom_report = build_geometry_from_machine_dir(machine_dir=machine_dir)
            write_json(run_dir / "probe_geometry_report.json", geom_report)
            if geom is not None:
                write_geometry_pickle(run_dir / "magnetic_probes.pickle", geom)
                write_geometry_pickle_internal(run_dir / "magnetic_probes_internal.pickle", geom)
                write_geometry_json(run_dir / "magnetic_probes.json", geom)
                _stage("probe_geometry", True, n_flux_loops=len(geom.flux_loops), n_pickup=len(geom.pickup_coils))
            else:
                if not self.cfg.allow_missing_geometry:
                    blocking_errors.append("probe_geometry_missing_or_invalid (see probe_geometry_report.json)")
                    _stage("probe_geometry", False, report=geom_report)
                else:
                    _stage(
                        "probe_geometry",
                        False,
                        report=geom_report,
                        note="allow_missing_geometry=True: continuing without magnetic_probes outputs",
                    )

            # Categorized experimental FAIR-MAST pack (CSV + plots). Non-blocking:
            # FreeGSNKE path must still run if plotting fails on a headless box.
            if getattr(self.cfg, "enable_experimental_data", True):
                try:
                    ed_report = build_experimental_data(
                        run_dir,
                        shot=int(shot),
                        cache_dir=shot_cache,
                        machine_dir=ma_root if ma_root is not None else machine_dir,
                        repo_root=repo_root,
                        include_l1=bool(getattr(self.cfg, "experimental_data_include_l1", True)),
                        include_l3=bool(getattr(self.cfg, "experimental_data_include_l3", True)),
                        plots=bool(getattr(self.cfg, "experimental_data_plots", True)),
                    )
                    write_json(run_dir / "experimental_data_report.json", ed_report.to_dict())
                    _stage(
                        "experimental_data",
                        bool(ed_report.ok),
                        n_files=len(ed_report.files_written),
                        n_plots=len(ed_report.plots_written),
                        warnings=list(ed_report.warnings)[:20],
                        errors=list(ed_report.errors),
                    )
                    if not ed_report.ok:
                        # Soft: record but do not block FreeGSNKE (inputs already extracted).
                        pass
                except Exception as e:
                    _stage("experimental_data", False, error=str(e))
                    write_json(
                        run_dir / "experimental_data_report.json",
                        {"ok": False, "errors": [str(e)]},
                    )
            else:
                _stage("experimental_data", True, note="enable_experimental_data=false")

            # Optional: execute FreeGSNKE scripts (inverse/forward) and compute residual metrics.
            exec_summary: Dict[str, Any] = {"enabled": bool(self.cfg.execute_freegsnke), "mode": self.cfg.freegsnke_run_mode}
            metrics_summary: Optional[Dict[str, Any]] = None
            if self.cfg.execute_freegsnke and blocking_errors:
                # Fail closed: never burn FreeGSNKE compute on a run whose
                # inputs/authorities are already known to be invalid.
                exec_summary.update({"skipped": "blocking_errors_present", "results": []})
                write_execution_report(run_dir, exec_summary)
                _stage(
                    "freegsnke_execute",
                    False,
                    note="skipped_fail_closed_due_to_blocking_errors",
                    blocking_errors=list(blocking_errors),
                )
            elif self.cfg.execute_freegsnke:
                mode = (self.cfg.freegsnke_run_mode or "none").lower()
                if mode not in {"none", "inverse", "forward", "both"}:
                    blocking_errors.append(f"invalid_freegsnke_run_mode: {mode}")
                    _stage("freegsnke_execute", False, error=f"invalid mode '{mode}'")
                else:
                    runner = FreeGSNKERunner(
                        python_exe=self.cfg.freegsnke_python,
                        timeout_s=self.cfg.freegsnke_script_timeout_s,
                        repo_root=repo_root,
                    )
                    results: List[Dict[str, Any]] = []
                    if mode in {"inverse", "both"}:
                        inv = run_dir / "inverse_run.py"
                        if not inv.exists():
                            blocking_errors.append("missing_inverse_run.py")
                            results.append({"script": "inverse_run.py", "ok": False, "error": "missing"})
                        else:
                            r = runner.run_script(inv, run_dir=run_dir, label="inverse")
                            results.append(r.__dict__)
                            if not r.ok:
                                blocking_errors.append(f"freegsnke_inverse_failed (see {r.stderr_path})")

                    if mode in {"forward", "both"}:
                        fwd = run_dir / "forward_run.py"
                        if not fwd.exists():
                            blocking_errors.append("missing_forward_run.py")
                            results.append({"script": "forward_run.py", "ok": False, "error": "missing"})
                        else:
                            r = runner.run_script(fwd, run_dir=run_dir, label="forward")
                            results.append(r.__dict__)
                            if not r.ok:
                                blocking_errors.append(f"freegsnke_forward_failed (see {r.stderr_path})")

                    exec_summary.update({"results": results})
                    write_execution_report(run_dir, exec_summary)
                    _stage("freegsnke_execute", all(bool(x.get("ok")) for x in results) if results else False, n_scripts=len(results))

                    if self.cfg.export_torax_geometry and mode in {"inverse", "both"}:
                        tg_auth_snap = (
                            inputs_dir
                            / "torax_geometry_export_authority"
                            / "torax_geometry_export_authority.json"
                        )
                        geqdsk_ok = False
                        geqdsk_path = None
                        if tg_auth_snap.exists():
                            try:
                                from .torax_geometry_export import load_torax_geometry_export_authority

                                _tg = load_torax_geometry_export_authority(tg_auth_snap)
                                geqdsk_path = run_dir / _tg.output_relpath
                                geqdsk_ok = geqdsk_path.is_file() and geqdsk_path.stat().st_size > 0
                            except Exception as e:
                                blocking_errors.append(
                                    f"torax_geometry_export_verify_failed: {type(e).__name__}: {e}"
                                )
                        if geqdsk_ok:
                            _stage(
                                "torax_geometry_export",
                                True,
                                path=str(geqdsk_path),
                            )
                        else:
                            blocking_errors.append(
                                "torax_geometry_export_missing: expected GEQDSK under "
                                "downstream/torax/ after inverse (ADR-001 fail-closed when "
                                "export_torax_geometry=true)"
                            )
                            _stage("torax_geometry_export", False, path=str(geqdsk_path))

                    # Evolutive forward (FAIR-MAST voltages) after successful inverse IC
                    if self.cfg.execute_evolutive:
                        evo_script = run_dir / "evolutive_run.py"
                        inv_ok = any(
                            str(x.get("script")) == "inverse_run.py" and bool(x.get("ok"))
                            for x in results
                        )
                        if not evo_script.exists():
                            blocking_errors.append("missing_evolutive_run.py")
                            _stage("evolutive_execute", False, error="missing_script")
                        elif not inv_ok:
                            blocking_errors.append(
                                "evolutive_requires_successful_inverse: inverse_dump.pkl IC missing/failed"
                            )
                            _stage("evolutive_execute", False, note="inverse_not_ok")
                        elif not (inputs_dir / "pf_voltages.csv").exists():
                            blocking_errors.append(
                                "evolutive_requires_pf_voltages: inputs/pf_voltages.csv missing"
                            )
                            _stage("evolutive_execute", False, note="missing_pf_voltages")
                        else:
                            # Prefer evolutive_authority script_timeout_s when declared
                            evo_timeout = self.cfg.freegsnke_script_timeout_s
                            evo_auth_path = inputs_dir / "evolutive_authority" / "evolutive_authority.json"
                            if evo_auth_path.exists():
                                try:
                                    evo_timeout = float(
                                        json.loads(evo_auth_path.read_text(encoding="utf-8")).get(
                                            "script_timeout_s", evo_timeout
                                        )
                                    )
                                except Exception:
                                    pass
                            evo_runner = FreeGSNKERunner(
                                python_exe=self.cfg.freegsnke_python,
                                timeout_s=evo_timeout,
                                repo_root=repo_root,
                            )
                            er = evo_runner.run_script(evo_script, run_dir=run_dir, label="evolutive")
                            results.append(er.__dict__)
                            exec_summary["results"] = results
                            exec_summary["evolutive"] = er.__dict__
                            write_execution_report(run_dir, exec_summary)
                            if not er.ok:
                                n_partial = evolutive_partial_history_n(run_dir)
                                # Hung/timed-out nlstepper after useful steps: keep
                                # inverse/forward success; do not fail-closed the shot.
                                if (er.timed_out or int(er.returncode) == 124) and n_partial >= 1:
                                    _stage(
                                        "evolutive_execute",
                                        False,
                                        error_hint=er.error_hint or "freegsnke_script_timeout",
                                        note="partial_timeout_with_history",
                                        n_steps_recorded=n_partial,
                                        duration_s=er.duration_s,
                                    )
                                else:
                                    blocking_errors.append(
                                        f"freegsnke_evolutive_failed (see {er.stderr_path})"
                                    )
                                    _stage("evolutive_execute", False, error_hint=er.error_hint)
                            else:
                                _stage("evolutive_execute", True, duration_s=er.duration_s)
                    else:
                        _stage("evolutive_execute", True, note="execute_evolutive=false")

                    # Contract-driven extraction + residual metrics (deterministic authority)
                    if self.cfg.enable_contract_metrics and self.cfg.diagnostic_contracts_path:
                        try:
                            cpath = _resolve_config_path(self.cfg.diagnostic_contracts_path, repo_root)
                            if cpath is None or not cpath.exists():
                                raise FileNotFoundError(
                                    f"diagnostic_contracts_path not found: {self.cfg.diagnostic_contracts_path}"
                                )
                            # Merge synthesizable calibration contracts (omit until authority present)
                            contracts_path_for_run = cpath
                            cal_path_m = _resolve_config_path(self.cfg.diagnostic_calibration_path, repo_root)
                            if cal_path_m is not None and cal_path_m.exists():
                                cal_m = load_diagnostic_calibration(cal_path_m)
                                if cal_m.n_synthesizable > 0:
                                    merged_path = run_dir / "contracts" / "diagnostic_contracts.merged.json"
                                    merge_calibration_contracts(cpath, cal_m, out_path=merged_path)
                                    contracts_path_for_run = merged_path
                            contracts = resolve_contracts_for_run(contracts_path_for_run, run_dir)
                            # Require files when metrics enabled (fail-closed).
                            contracts_report = validate_contracts(contracts, require_files=True)
                            write_resolved_contracts(run_dir, contracts)
                            if not contracts_report.get("ok", False):
                                blocking_errors.append(
                                    "contracts_invalid: " + "; ".join(contracts_report.get("errors", []))
                                )
                                _stage("contracts", False, errors=contracts_report.get("errors"))
                            else:
                                syn_res = extract_synthetic_by_contracts(run_dir, contracts)
                                _stage(
                                    "synthetic_extract",
                                    syn_res.ok,
                                    n_written=len(syn_res.written),
                                    errors=syn_res.errors,
                                )
                                if not syn_res.ok:
                                    blocking_errors.append(
                                        "synthetic_extract_failed: " + "; ".join(syn_res.errors)
                                    )
                                metrics_summary = compare_from_contracts(run_dir, contracts)
                                metrics_ok = bool(metrics_summary.get("ok", False)) and int(
                                    metrics_summary.get("n_scored", 0)
                                ) > 0
                                _stage(
                                    "residual_metrics_contracts",
                                    metrics_ok,
                                    n_scored=metrics_summary.get("n_scored"),
                                    n_skipped_all_nan=metrics_summary.get("n_skipped_all_nan"),
                                    errors=metrics_summary.get("errors"),
                                )
                                if not metrics_ok:
                                    blocking_errors.append(
                                        "residual_metrics_failed: "
                                        + (
                                            "; ".join(metrics_summary.get("errors", []))
                                            or f"n_scored={metrics_summary.get('n_scored')}"
                                        )
                                    )
                        except Exception as e:
                            # Contract system errors are blocking when explicitly enabled.
                            blocking_errors.append(f"contracts_failed: {type(e).__name__}: {e}")
                            _stage("contracts", False, error=str(e))
                    else:
                        _stage("contracts", True, note="contract_metrics_disabled_or_no_contracts_path")

            # Final status (recomputed again immediately before each manifest write below)
            status = "success" if not blocking_errors else "failed"

            science_audit = None
            try:
                from .science_audit import build_science_audit

                science_audit = build_science_audit(run_dir)
                _stage(
                    "science_audit",
                    True,
                    reconstruction_hint=(science_audit.get("reconstruction_quality") or {}).get(
                        "science_tier_hint"
                    ),
                    evolutive_ip_ok=(science_audit.get("evolutive_ip") or {}).get("ok"),
                )
            except Exception as e:
                _stage("science_audit", False, error=str(e))
                science_audit = None

            efit_compare_report: Optional[Dict[str, Any]] = None
            if self.cfg.compare_efit_archive and shot_cache is not None:
                try:
                    from .efit_compare import load_efit_compare_authority, run_efit_compare

                    ec_snap = (
                        inputs_dir / "efit_compare_authority" / "efit_compare_authority.json"
                    )
                    if not ec_snap.exists():
                        raise FileNotFoundError("efit_compare_authority snapshot missing")
                    ec_auth = load_efit_compare_authority(ec_snap)
                    ecr = run_efit_compare(
                        run_dir,
                        shot=int(shot),
                        cache_dir=shot_cache,
                        auth=ec_auth,
                    )
                    efit_compare_report = ecr.to_dict()
                    write_json(run_dir / "04_efit_compare" / "COMPARE.json", efit_compare_report)
                    if ecr.ok:
                        _stage(
                            "efit_compare",
                            True,
                            t_efit=ecr.t_efit,
                            n_plots=len(ecr.plots_written),
                        )
                    else:
                        _stage(
                            "efit_compare",
                            False,
                            errors=list(ecr.errors)[:5],
                            fix_hint=ecr.fix_hint,
                        )
                        if ec_auth.fail_closed_if_missing:
                            blocking_errors.append(
                                "efit_compare_failed: "
                                + ("; ".join(ecr.errors) or "unknown")
                                + (f" | {ecr.fix_hint}" if ecr.fix_hint else "")
                            )
                except Exception as e:
                    _stage("efit_compare", False, error=str(e))
                    efit_compare_report = {"ok": False, "errors": [str(e)]}
                    write_json(run_dir / "04_efit_compare" / "COMPARE.json", efit_compare_report)
                    # Exceptions during a requested compare are fail-closed when the
                    # authority asks for it; otherwise still record a loud soft failure.
                    try:
                        from .efit_compare import load_efit_compare_authority

                        ec_snap = (
                            inputs_dir / "efit_compare_authority" / "efit_compare_authority.json"
                        )
                        if ec_snap.exists() and load_efit_compare_authority(ec_snap).fail_closed_if_missing:
                            blocking_errors.append(f"efit_compare_exception: {type(e).__name__}: {e}")
                    except Exception:
                        pass
            else:
                _stage(
                    "efit_compare",
                    True,
                    note="compare_efit_archive=false_or_no_cache",
                )

            # ADR-004 Phase 2: optional GSPulse-style planner (default off)
            if self.cfg.execute_planner and final_tw is not None:
                try:
                    from .planner import run_planner_stage

                    pl_snap = inputs_dir / "planner_authority" / "planner_authority.json"
                    cl_snap = inputs_dir / "coil_limits_authority" / "coil_limits_authority.json"
                    if not pl_snap.exists() or not cl_snap.exists():
                        raise FileNotFoundError("planner/coil_limits authority snapshots missing")
                    pl_auth = load_planner_authority(pl_snap)
                    cl_auth = load_coil_limits(cl_snap)
                    if not pl_auth.enabled:
                        msg = (
                            "execute_planner=true but planner_authority.enabled=false — "
                            "enable the authority or set execute_planner=false"
                        )
                        _stage("planner", False, note="planner_authority.enabled=false")
                        blocking_errors.append(f"planner_required: {msg}")
                    else:
                        vm_path = _resolve_config_path(self.cfg.voltage_map_path, repo_root)
                        if vm_path is None or not vm_path.exists():
                            raise FileNotFoundError("voltage_map_path required for planner circuit order")
                        vmap = load_voltage_map(vm_path)
                        order = list(vmap.machine_active_circuit_order)
                        ma_for_plan = ma_root if ma_root is not None else machine_dir

                        from .coil_limits import resolve_measured_peak_limits, write_coil_limits

                        R_for_limits: dict = {}
                        L_for_limits: dict = {}
                        cd_snap_early = (
                            inputs_dir
                            / "circuit_dynamics_authority"
                            / "circuit_dynamics_authority.json"
                        )
                        if cd_snap_early.exists():
                            from .circuit_dynamics_authority import load_circuit_dynamics_authority

                            _cd_early = load_circuit_dynamics_authority(cd_snap_early)
                            R_for_limits = {
                                name: float(rl.R_ohm) for name, rl in _cd_early.circuits.items()
                            }
                            L_for_limits = {
                                name: float(rl.L_henry) for name, rl in _cd_early.circuits.items()
                            }

                        if cl_auth.limit_policy == "measured_peak_margin":
                            cl_auth = resolve_measured_peak_limits(
                                cl_auth,
                                inputs_dir=inputs_dir,
                                circuit_order=order,
                                t_start=float(final_tw.t_start),
                                t_end=float(final_tw.t_end),
                                R_ohm_by_circuit=R_for_limits or None,
                                L_henry_by_circuit=L_for_limits or None,
                                n_knots=int(pl_auth.n_knots),
                            )
                            write_coil_limits(inputs_dir, cl_auth)

                        # Prefer cited circuit_dynamics_authority (user PF R/L); FreeGSNKE fills gaps.
                        dyn = None
                        snap_dyn = inputs_dir / "circuit_dynamics_snapshot.json"
                        cd_snap = (
                            inputs_dir / "circuit_dynamics_authority" / "circuit_dynamics_authority.json"
                        )
                        freegsnke_fill = None
                        if snap_dyn.exists() and not cd_snap.exists():
                            from .planner import load_circuit_dynamics

                            dyn = load_circuit_dynamics(snap_dyn)
                        else:
                            try:
                                from .planner import extract_circuit_dynamics_from_freegsnke_machine

                                freegsnke_fill = extract_circuit_dynamics_from_freegsnke_machine(
                                    machine_dir=ma_for_plan,
                                    circuit_order=order,
                                )
                            except Exception:
                                import os as _os
                                import subprocess
                                import sys

                                from .planner import load_circuit_dynamics

                                py = self.cfg.freegsnke_python or sys.executable
                                md_lit = json.dumps(str(Path(ma_for_plan).resolve()))
                                out_lit = json.dumps(str(Path(snap_dyn).resolve()))
                                order_lit = json.dumps(list(order))
                                script = (
                                    "import json\n"
                                    "from pathlib import Path\n"
                                    "from mast_freegsnke.planner import ("
                                    "extract_circuit_dynamics_from_freegsnke_machine, "
                                    "write_circuit_dynamics)\n"
                                    f"order=json.loads({order_lit!r})\n"
                                    f"md=Path(json.loads({md_lit!r}))\n"
                                    f"out=Path(json.loads({out_lit!r}))\n"
                                    "dyn=extract_circuit_dynamics_from_freegsnke_machine("
                                    "machine_dir=md, circuit_order=order)\n"
                                    "write_circuit_dynamics(out, dyn)\n"
                                    "print('ok')\n"
                                )
                                env = dict(**{k: v for k, v in _os.environ.items()})
                                src_path = str((repo_root / "src").resolve())
                                prev = env.get("PYTHONPATH", "")
                                env["PYTHONPATH"] = (
                                    src_path + ((_os.pathsep + prev) if prev else "")
                                )
                                r = subprocess.run(
                                    [str(py), "-c", script],
                                    capture_output=True,
                                    text=True,
                                    env=env,
                                    timeout=300,
                                )
                                if r.returncode == 0 and snap_dyn.exists():
                                    freegsnke_fill = load_circuit_dynamics(snap_dyn)

                            if cd_snap.exists():
                                from .circuit_dynamics_authority import (
                                    build_circuit_dynamics_from_authority,
                                    load_circuit_dynamics_authority,
                                )
                                from .planner import write_circuit_dynamics

                                cd_auth = load_circuit_dynamics_authority(cd_snap)
                                dyn, _fill_meta = build_circuit_dynamics_from_authority(
                                    cd_auth,
                                    circuit_order=order,
                                    machine_dir=ma_for_plan,
                                    freegsnke_fill=freegsnke_fill,
                                )
                                write_circuit_dynamics(snap_dyn, dyn)
                            elif freegsnke_fill is not None:
                                from .planner import write_circuit_dynamics

                                dyn = freegsnke_fill
                                write_circuit_dynamics(snap_dyn, dyn)
                            elif snap_dyn.exists():
                                from .planner import load_circuit_dynamics

                                dyn = load_circuit_dynamics(snap_dyn)
                            else:
                                raise RuntimeError(
                                    "circuit_dynamics unavailable: cite circuit_dynamics_authority "
                                    "and/or provide FreeGSNKE machine R/L extract"
                                )

                        prep = run_planner_stage(
                            run_dir=run_dir,
                            inputs_dir=inputs_dir,
                            machine_dir=ma_for_plan,
                            planner_auth=pl_auth,
                            coil_limits=cl_auth,
                            circuit_order=order,
                            t_start=float(final_tw.t_start),
                            t_end=float(final_tw.t_end),
                            shot=int(shot),
                            circuit_dynamics=dyn,
                        )
                        _stage(
                            "planner",
                            True,
                            path=prep.get("path"),
                            n_knots=prep.get("n_knots"),
                            residual_rms=prep.get("residual_rms_by_circuit"),
                            n_voltage_violations=prep.get("n_voltage_violations_raw"),
                        )
                except Exception as e:
                    _stage("planner", False, error=str(e))
                    blocking_errors.append(f"planner_failed: {type(e).__name__}: {e}")
            elif self.cfg.execute_planner:
                _stage("planner", False, note="no_window")
                blocking_errors.append("planner_failed: window not finalized")
            else:
                _stage("planner", True, note="execute_planner=false")

            status = "success" if not blocking_errors else "failed"
            _write_manifest(
                {
                    "cache_dir": str(shot_cache) if shot_cache is not None else None,
                    "download_report": download_report,
                    "extract_meta": extract_meta,
                    "time_window": final_tw.__dict__ if final_tw is not None else None,
                    "time_window_qc": window_diag.__dict__ if window_diag is not None else None,
                    "time_window_override": window_override,
                    "time_window_consensus": consensus_obj.__dict__ if consensus_obj is not None else None,
                    "freegsnke_execution": exec_summary,
                    "reconstruction_metrics": metrics_summary,
                    "science_audit": science_audit,
                    "efit_compare": efit_compare_report,
                    "machine_authority_snapshot": machine_snapshot,
                    "diagnostic_calibration_snapshot": calibration_snapshot,
                    "diagnostic_calibration_apply": calibration_apply,
                }
            )

            # Expert overlay (pre-layout paths still valid for metrics/evolutive)
            try:
                base_for_summary = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
                overlay = write_shot_expert_overlay(
                    run_dir,
                    shot=shot,
                    manifest=base_for_summary,
                    science_audit=science_audit,
                )
                _stage("shot_expert_overlay", True, **overlay)
            except Exception as e:
                _stage("shot_expert_overlay", False, error=str(e))

            # Provenance before folder rearrange (writes provenance/ at run root)
            try:
                # Scrub stale absolute-target junctions left in history/ from prior layouts.
                _sanitize_history_reparse_points(run_dir)
                base_manifest = json.loads((run_dir / "manifest.json").read_text())
                hash_data_tree = shot_cache if (self.cfg.provenance_hash_data and shot_cache is not None) else None
                prov_summary = write_provenance(run_dir=run_dir, repo_root=repo_root, hash_data_tree=hash_data_tree)
                write_manifest_v2(
                    run_dir=run_dir,
                    base_manifest=base_manifest,
                    provenance_summary=prov_summary,
                    machine_snapshot=machine_snapshot,
                )
                _stage("provenance_lock", True, data_hashed=bool(hash_data_tree is not None))
            except Exception as e:
                _stage("provenance_lock", False, error=str(e))
                if self.cfg.require_machine_authority:
                    blocking_errors.append(f"provenance_lock_failed: {type(e).__name__}: {e}")

            # Numbered expert layout last (moves metrics/contracts/provenance/…)
            try:
                from .shot_layout import finalize_shot_layout

                layout_index = finalize_shot_layout(run_dir, shot=int(shot))
                _stage("shot_layout", True, n_moves=len(layout_index.get("moves") or []))
                # Refresh START_HERE / SUMMARY key paths after moves
                try:
                    base_for_summary = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
                    write_shot_expert_overlay(
                        run_dir,
                        shot=shot,
                        manifest=base_for_summary,
                        science_audit=science_audit,
                    )
                except Exception:
                    pass
            except Exception as e:
                _stage("shot_layout", False, error=str(e))

            status = "success" if not blocking_errors else "failed"
            _write_manifest(
                {
                    "cache_dir": str(shot_cache) if shot_cache is not None else None,
                    "download_report": download_report,
                    "extract_meta": extract_meta,
                    "time_window": final_tw.__dict__ if final_tw is not None else None,
                    "time_window_qc": window_diag.__dict__ if window_diag is not None else None,
                    "time_window_override": window_override,
                    "time_window_consensus": consensus_obj.__dict__ if consensus_obj is not None else None,
                    "freegsnke_execution": exec_summary,
                    "reconstruction_metrics": metrics_summary,
                    "science_audit": science_audit,
                    "efit_compare": efit_compare_report,
                    "machine_authority_snapshot": machine_snapshot,
                    "diagnostic_calibration_snapshot": calibration_snapshot,
                    "diagnostic_calibration_apply": calibration_apply,
                }
            )

            if blocking_errors:
                raise RuntimeError("Pipeline completed with blocking errors: " + "; ".join(blocking_errors))

            return run_dir

        except Exception as e:
            status = "failed"
            _write_manifest(
                {
                    "cache_dir": str(shot_cache) if shot_cache is not None else None,
                    "download_report": download_report,
                    "extract_meta": extract_meta,
                    "exception": {"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc()},
                }
            )
            raise