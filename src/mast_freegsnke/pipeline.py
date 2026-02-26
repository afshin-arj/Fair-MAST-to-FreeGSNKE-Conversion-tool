
from __future__ import annotations

import json
import platform
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .availability import check_groups
from .config import AppConfig
from .download import BulkDownloader
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
from .freegsnke_runner import FreeGSNKERunner, write_execution_report
from .diagnostic_contracts import load_contracts, validate_contracts, write_resolved_contracts
from .coil_map import load_coil_map, validate_coil_map, write_resolved_coil_map
from .synthetic_extract import extract_synthetic_by_contracts
from .metrics import compare_from_contracts
from .execution_authority import write_execution_authority


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

        runs_root = ensure_dir(self.cfg.runs_dir)
        run_dir = ensure_dir(runs_root / f"shot_{shot}")
        inputs_dir = ensure_dir(run_dir / "inputs")


        def _stage(name: str, ok: bool, **kw: Any) -> None:
            stage_log.append({"stage": name, "ok": bool(ok), **kw})

        repo_root = self.templates_dir.parent

        # Machine authority (optional but strongly recommended for reviewer-grade runs).
        # If present, it is validated and snapshotted into the run directory.
        machine_snapshot = None
        ma_root = None
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
                "level2_s3_prefix": self.cfg.level2_s3_prefix,
                "s3_layout_patterns": list(self.cfg.s3_layout_patterns),
                "cache_root": str(self.cfg.cache_dir),
                "machine_dir": str(machine_dir),
                "formed_plasma_frac": float(self.cfg.formed_plasma_frac),
            }
            manifest.update(extra)
            write_json(run_dir / "manifest.json", manifest)

        cache_root = ensure_dir(self.cfg.cache_dir)
        shot_cache: Optional[Path] = None
        extract_meta: Dict[str, Any] = {}
        exec_summary: Dict[str, Any] = {}
        metrics_summary: Any = None
        contracts_report: Any = None

        # Always attempt to write a manifest, even on failure.
        try:
            client = MastAppClient(base_url=self.cfg.mastapp_base_url)
            if not client.shot_exists(shot):
                raise RuntimeError(f"Shot {shot} not available via MastApp REST at {self.cfg.mastapp_base_url}")
            _stage("mastapp_shot_exists", True)

            dl = BulkDownloader(
                s5cmd_path=self.cfg.s5cmd_path,
                level2_s3_prefix=self.cfg.level2_s3_prefix,
                layout_patterns=self.cfg.s3_layout_patterns,
            )

            # Pre-check group availability (no downloads yet)
            avail = check_groups(shot=shot, groups=self.cfg.required_groups, discover=dl.discover_group_path)
            write_json(cache_root / f"shot_{shot}" / "availability.json", {k: v.__dict__ for k, v in avail.items()})
            missing = [k for k, v in avail.items() if not v.exists]
            if missing:
                raise RuntimeError("Required Level-2 groups missing for shot {}: {}".format(shot, ", ".join(missing)))
            _stage("availability_check", True, groups_ok=list(avail.keys()))

            # Download now that availability is confirmed
            shot_cache = dl.download_groups(shot, self.cfg.required_groups, cache_root)
            _stage("download_groups", True, shot_cache=str(shot_cache))

            # Extract CSV inputs (optional stack)
            try:
                ex = Extractor(formed_plasma_frac=self.cfg.formed_plasma_frac)
                extract_meta = ex.extract(shot_cache, inputs_dir)
                _stage("extract_csv", True, meta=extract_meta)
            except Exception as e:
                extract_meta = {"extract_error": str(e)}
                _stage("extract_csv", False, error=str(e))
            write_json(inputs_dir / "extract_meta.json", extract_meta)

            # Generate run scripts/stubs
            gen = ScriptGenerator(templates_dir=self.templates_dir)
            gen.generate(run_dir=run_dir, machine_dir=machine_dir, formed_frac=self.cfg.formed_plasma_frac)
            _stage("generate_scripts", True)

            # Execution-state authority (v9): eliminate hidden defaults in generated scripts
            # by exporting an explicit authority bundle under inputs/execution_authority/.
            try:
                ea_root = write_execution_authority(inputs_dir)
                _stage("execution_authority", True, root=str(ea_root))
            except Exception as e:
                _stage("execution_authority", False, error=str(e))
                blocking_errors.append(f"execution_authority_write_failed:{e}")

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

            final_tw: TimeWindow
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
                final_tw = infer_time_window(inputs_dir=inputs_dir, formed_frac=self.cfg.formed_plasma_frac)

            write_json(inputs_dir / "window.json", final_tw.__dict__)
            _stage("window_finalize", True, t_start=final_tw.t_start, t_end=final_tw.t_end, source=final_tw.source)

            # QC diagnostics (best-effort, but failures are blocking if window exists)
            window_diag: Optional[WindowDiagnostics] = None
            try:
                window_diag = evaluate_time_window(inputs_dir=inputs_dir, tw=final_tw)
                write_json(inputs_dir / "window_diagnostics.json", window_diag.__dict__)
                (inputs_dir / "WINDOW_QC_REPORT.txt").write_text(format_diagnostics(window_diag))
                _stage("window_qc", True, confidence=window_diag.confidence, flags=window_diag.flags)
            except Exception as e:
                blocking_errors.append(f"window_qc_failed: {e}")
                _stage("window_qc", False, error=str(e))

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

            # Optional: execute FreeGSNKE scripts (inverse/forward) and compute residual metrics.
            exec_summary: Dict[str, Any] = {"enabled": bool(self.cfg.execute_freegsnke), "mode": self.cfg.freegsnke_run_mode}
            metrics_summary: Optional[Dict[str, Any]] = None
            if self.cfg.execute_freegsnke:
                mode = (self.cfg.freegsnke_run_mode or "none").lower()
                if mode not in {"none", "inverse", "forward", "both"}:
                    blocking_errors.append(f"invalid_freegsnke_run_mode: {mode}")
                    _stage("freegsnke_execute", False, error=f"invalid mode '{mode}'")
                else:
                    runner = FreeGSNKERunner(python_exe=self.cfg.freegsnke_python)
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

                    # Contract-driven extraction + residual metrics (deterministic authority)
                    if self.cfg.enable_contract_metrics and self.cfg.diagnostic_contracts_path:
                        try:
                            cpath = Path(self.cfg.diagnostic_contracts_path)
                            contracts = load_contracts(cpath, base_dir=cpath.parent)
                            contracts_report = validate_contracts(contracts, require_files=False)
                            # Always write resolved contracts into run folder for audit (absolute paths).
                            write_resolved_contracts(run_dir, contracts)

                            # Optional coil map authority (for PF mapping governance; not yet wired into FreeGSNKE templates).
                            if self.cfg.coil_map_path:
                                cm_path = Path(self.cfg.coil_map_path)
                                coil_map = load_coil_map(cm_path)
                                cm_report = validate_coil_map(coil_map)
                                write_resolved_coil_map(run_dir, coil_map)
                                if not cm_report.get("ok", False):
                                    blocking_errors.append("coil_map_invalid: " + "; ".join(cm_report.get("errors", [])))
                                    _stage("coil_map", False, n=cm_report.get("n"), errors=cm_report.get("errors"))
                                else:
                                    _stage("coil_map", True, n=cm_report.get("n"))
                            else:
                                _stage("coil_map", True, note="no_coil_map_path")

                            # Normalize synthetic traces as specified by contracts (best effort)
                            syn_res = extract_synthetic_by_contracts(run_dir, contracts)
                            _stage("synthetic_extract", syn_res.ok, n_written=len(syn_res.written), errors=syn_res.errors)

                            # Compute residuals (best effort, but if contracts exist this is usually desired)
                            metrics_summary = compare_from_contracts(run_dir, contracts)
                            _stage("residual_metrics_contracts", metrics_summary.get("ok", False), n_scored=metrics_summary.get("n_scored"), errors=metrics_summary.get("errors"))
                        except Exception as e:
                            # Contract system errors are blocking when explicitly enabled.
                            blocking_errors.append(f"contracts_failed: {type(e).__name__}: {e}")
                            _stage("contracts", False, error=str(e))
                    else:
                        _stage("contracts", True, note="contract_metrics_disabled_or_no_contracts_path")

            # Final status
            status = "success" if not blocking_errors else "failed"

            _write_manifest(
                {
                    "cache_dir": str(shot_cache) if shot_cache is not None else None,
                    "extract_meta": extract_meta,
                    "time_window": final_tw.__dict__,
                    "time_window_qc": window_diag.__dict__ if window_diag is not None else None,
                    "time_window_override": window_override,
                    "time_window_consensus": consensus_obj.__dict__ if consensus_obj is not None else None,
                    "freegsnke_execution": exec_summary,
                    "reconstruction_metrics": metrics_summary,
                    "machine_authority_snapshot": machine_snapshot,
                }
            )

            # Reproducibility lock (hash run artifacts + environment capture) and manifest v2.
            try:
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
            if blocking_errors:
                raise RuntimeError("Pipeline completed with blocking errors: " + "; ".join(blocking_errors))

            return run_dir

        except Exception as e:
            status = "failed"
            _write_manifest(
                {
                    "cache_dir": str(shot_cache) if shot_cache is not None else None,
                    "extract_meta": extract_meta,
                    "exception": {"type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc()},
                }
            )
            raise