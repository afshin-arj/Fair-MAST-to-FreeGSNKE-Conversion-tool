from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None

@dataclass(frozen=True)
class AppConfig:
    mastapp_base_url: str
    required_groups: List[str]
    # Best-effort Level-2 groups (e.g. pf_passive for audit). Missing is WARN, not blocking.
    optional_groups: List[str]
    level2_s3_prefix: str
    s5cmd_path: str
    # Optional S3 endpoint URL (MAST uses https://s3.echo.stfc.ac.uk)
    s3_endpoint_url: Optional[str]
    # If True, use anonymous S3 access (--no-sign-request)
    s3_no_sign_request: bool
    # Timeout for s5cmd operations (seconds). Prevents indefinite hangs.
    s5cmd_timeout_s: int
    runs_dir: Path
    cache_dir: Path
    formed_plasma_frac: float
    s3_layout_patterns: List[str]
    allow_missing_geometry: bool

    # Optional: execute FreeGSNKE scripts after generating a run folder.
    execute_freegsnke: bool
    # one of: none | inverse | forward | both
    freegsnke_run_mode: str
    # Optional python interpreter path for FreeGSNKE environment; defaults to current interpreter.
    freegsnke_python: Optional[str]

    # Optional residual comparison configuration.
    # Each entry is a dict contract that describes how to compare experimental vs synthetic traces.
    diagnostics_compare: List[Dict[str, Any]]

    # Optional: path to diagnostic contracts authority JSON.
    diagnostic_contracts_path: Optional[str]
    # Optional: path to diagnostic calibration authority (mirnov/saddle/omaha).
    # Empty channels / awaiting_authority keeps those families audit-only.
    diagnostic_calibration_path: Optional[str]
    # Optional: path to PF/coil mapping authority JSON.
    coil_map_path: Optional[str]
    # Optional: path to voltage_map authority (FAIR-MAST voltage channels → FreeGSNKE active vector).
    voltage_map_path: Optional[str]
    # Optional: path to evolutive_authority JSON (nl_solver numerics; fail-closed when execute_evolutive).
    evolutive_authority_path: Optional[str]
    # Optional: passive resistivity authority (awaiting = empty FreeGSNKE passives).
    passive_resistivity_path: Optional[str]
    # Enable contract-driven extraction + residual metrics (requires contracts).
    enable_contract_metrics: bool
    # Categorized experimental FAIR-MAST pack under SHOT/<N>/experimental_data/.
    enable_experimental_data: bool
    experimental_data_plots: bool
    experimental_data_include_l1: bool
    experimental_data_include_l3: bool
    # If True, generate+execute evolutive_run.py after static inverse (when voltage map + voltages exist).
    execute_evolutive: bool

    # Optional: machine authority directory (versioned geometry/registry).
    machine_authority_dir: Optional[str]
    # If True, missing/invalid machine authority is a blocking error.
    require_machine_authority: bool
    # If True, rebuild classic MAST pickles when wall/pf_active fingerprints disagree.
    rebuild_machine_authority: bool
    # If True, also hash downloaded data cache tree (can be expensive).
    provenance_hash_data: bool
    # If True, reuse non-empty data_cache/shot_<N>/<group>.zarr trees instead of re-syncing.
    allow_cache_reuse: bool
    # If True, a multi-shot batch stops at the first failing shot (remaining reported as skipped).
    batch_abort_on_failure: bool
    # Gate shots before download/execute: MastApp + required L2 availability (or cache).
    enable_shot_suitability_gate: bool
    # Declared window-end refine after formed-plasma start
    # (none | ip_peak_then_floor | ip_prepeak_floor).
    window_end_policy: str = "ip_prepeak_floor"
    # For ip_*_floor policies: floor = frac × |Ip|_peak (measured Ip only).
    # ip_prepeak_floor cuts before the peak (excludes pre-disruption spike);
    # ip_peak_then_floor cuts after the peak.
    window_end_ip_frac: float = 0.90
    # Number of deterministic window sample times for multi-time synthetic
    # diagnostics / residual scoring (rule: linspace_window_inclusive).
    metrics_n_times: int = 41
    # PNG frames + animated GIFs across the formed-plasma window (inverse/forward)
    # and evolutive steps (presentation only; no new interactive prompts).
    write_equilibrium_gifs: bool = True
    write_eq_frames: bool = True
    equilibrium_gif_fps: float = 2.0
    equilibrium_gif_dpi: int = 100
    # Optional ADR-001 FreeGSNKE → TORAX GEQDSK export (default off; not shot-only happy path).
    export_torax_geometry: bool = False
    torax_geometry_export_authority_path: Optional[str] = None
    # ADR-002: compare FreeGSNKE to FAIR-MAST EFIT++ archive (default.json sets true).
    compare_efit_archive: bool = False
    efit_compare_authority_path: Optional[str] = None
    # ADR-004 Phase 2: GSPulse-style planner (default off; hard-gated by coil_limits).
    execute_planner: bool = False
    # Optional ADR-004: second evolutive from 07_planner/planned_voltages.csv (default off).
    execute_evolutive_from_plan: bool = False
    planner_authority_path: Optional[str] = None
    plasma_scalars_authority_path: Optional[str] = None
    coil_limits_authority_path: Optional[str] = None
    # Optional cited PF R/L table (Solenoid may be FreeGSNKE-filled).
    circuit_dynamics_authority_path: Optional[str] = None
    # ADR-004: EFIT++ → profile_trajectory (default.json enables when path set).
    profile_trajectory_authority_path: Optional[str] = None
    build_profile_trajectory: bool = False
    # ADR-004 Path B1: EFIT++ shape targets for future isoflux/Picard.
    shape_targets_authority_path: Optional[str] = None
    build_shape_targets: bool = False
    # ADR-006: optional GSFit live reconstruction peer (gated until calib + Green’s).
    execute_gsfit: bool = False
    gsfit_authority_path: Optional[str] = None
    # Hard wall-clock limit for each FreeGSNKE script (seconds). None disables.
    # Protects the pipeline from FreeGSNKE's uncapped residual-resize hang.
    freegsnke_script_timeout_s: Optional[float] = 3600.0


    @staticmethod
    def load(path: Path) -> "AppConfig":
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        text = path.read_text(encoding="utf-8")
        suf = path.suffix.lower()
        if suf in (".yaml", ".yml"):
            if yaml is None:
                raise RuntimeError("YAML config requested but PyYAML is not installed. Use JSON or install pyyaml.")
            obj = yaml.safe_load(text) or {}
        else:
            obj = json.loads(text)

        # Normalize + defaults
        mastapp_base_url = str(obj.get("mastapp_base_url", "https://mastapp.site/json")).rstrip("/")
        required_groups = list(obj.get("required_groups", ["pf_active", "magnetics", "wall"]))
        optional_groups = list(obj.get("optional_groups", ["pf_passive"]))
        level2_s3_prefix = str(obj.get("level2_s3_prefix", ""))
        s5cmd_path = str(obj.get("s5cmd_path", "s5cmd"))
        s3_endpoint_url = (str(obj["s3_endpoint_url"]) if obj.get("s3_endpoint_url") else None)
        s3_no_sign_request = bool(obj.get("s3_no_sign_request", False))
        s5cmd_timeout_s = int(obj.get("s5cmd_timeout_s", 60))
        runs_dir = Path(obj.get("runs_dir", "SHOT"))
        cache_dir = Path(obj.get("cache_dir", "data_cache"))
        formed_plasma_frac = float(obj.get("formed_plasma_frac", 0.80))
        window_end_policy = str(obj.get("window_end_policy", "ip_prepeak_floor")).strip()
        window_end_ip_frac = float(obj.get("window_end_ip_frac", 0.90))
        if not (0.0 < window_end_ip_frac <= 1.0):
            raise ValueError(
                f"window_end_ip_frac must be in (0, 1] (got {window_end_ip_frac})"
            )
        _wep = window_end_policy.lower()
        if _wep not in (
            "none",
            "threshold_end",
            "formed_threshold",
            "ip_peak_then_floor",
            "ip_prepeak_floor",
        ):
            raise ValueError(
                f"window_end_policy must be none|threshold_end|ip_peak_then_floor|"
                f"ip_prepeak_floor (got {window_end_policy!r})"
            )
        allow_missing_geometry = bool(obj.get("allow_missing_geometry", False))

        execute_freegsnke = bool(obj.get("execute_freegsnke", False))
        freegsnke_run_mode = str(obj.get("freegsnke_run_mode", "none")).lower()
        freegsnke_python = (str(obj["freegsnke_python"]) if obj.get("freegsnke_python") else None)

        diagnostics_compare = list(obj.get("diagnostics_compare", []))
        diagnostic_contracts_path = (str(obj["diagnostic_contracts_path"]) if obj.get("diagnostic_contracts_path") else None)
        diagnostic_calibration_path = (
            str(obj["diagnostic_calibration_path"]) if obj.get("diagnostic_calibration_path") else None
        )
        coil_map_path = (str(obj["coil_map_path"]) if obj.get("coil_map_path") else None)
        voltage_map_path = (str(obj["voltage_map_path"]) if obj.get("voltage_map_path") else None)
        evolutive_authority_path = (
            str(obj["evolutive_authority_path"]) if obj.get("evolutive_authority_path") else None
        )
        profile_trajectory_authority_path = (
            str(obj["profile_trajectory_authority_path"])
            if obj.get("profile_trajectory_authority_path")
            else None
        )
        build_profile_trajectory = bool(obj.get("build_profile_trajectory", False))
        if build_profile_trajectory and not profile_trajectory_authority_path:
            raise ValueError(
                "build_profile_trajectory=true requires profile_trajectory_authority_path "
                "(ADR-004 fail-closed)"
            )
        shape_targets_authority_path = (
            str(obj["shape_targets_authority_path"])
            if obj.get("shape_targets_authority_path")
            else None
        )
        build_shape_targets = bool(obj.get("build_shape_targets", False))
        if build_shape_targets and not shape_targets_authority_path:
            raise ValueError(
                "build_shape_targets=true requires shape_targets_authority_path "
                "(ADR-004 Path B1 fail-closed)"
            )
        # Ensure equilibrium group is downloaded when building profile / shape targets
        if build_profile_trajectory and "equilibrium" not in optional_groups:
            optional_groups = list(optional_groups) + ["equilibrium"]
        if build_shape_targets and "equilibrium" not in optional_groups:
            optional_groups = list(optional_groups) + ["equilibrium"]
        passive_resistivity_path = (
            str(obj["passive_resistivity_path"]) if obj.get("passive_resistivity_path") else None
        )
        enable_contract_metrics = bool(obj.get("enable_contract_metrics", False))
        enable_experimental_data = bool(obj.get("enable_experimental_data", True))
        experimental_data_plots = bool(obj.get("experimental_data_plots", True))
        experimental_data_include_l1 = bool(obj.get("experimental_data_include_l1", True))
        experimental_data_include_l3 = bool(obj.get("experimental_data_include_l3", True))
        execute_evolutive = bool(obj.get("execute_evolutive", False))
        execute_evolutive_from_plan = bool(obj.get("execute_evolutive_from_plan", False))

        machine_authority_dir = (str(obj["machine_authority_dir"]) if obj.get("machine_authority_dir") else None)
        require_machine_authority = bool(obj.get("require_machine_authority", False))
        rebuild_machine_authority = bool(obj.get("rebuild_machine_authority", True))
        provenance_hash_data = bool(obj.get("provenance_hash_data", False))
        allow_cache_reuse = bool(obj.get("allow_cache_reuse", True))
        batch_abort_on_failure = bool(obj.get("batch_abort_on_failure", False))
        enable_shot_suitability_gate = bool(obj.get("enable_shot_suitability_gate", True))
        metrics_n_times = int(obj.get("metrics_n_times", 41))
        if metrics_n_times < 1 or metrics_n_times > 101:
            raise ValueError(
                f"metrics_n_times must be in [1, 101] (got {metrics_n_times})"
            )
        write_equilibrium_gifs = bool(obj.get("write_equilibrium_gifs", True))
        write_eq_frames = bool(obj.get("write_eq_frames", True))
        if write_equilibrium_gifs and not write_eq_frames:
            raise ValueError(
                "write_equilibrium_gifs=true requires write_eq_frames=true"
            )
        equilibrium_gif_fps = float(obj.get("equilibrium_gif_fps", 2.0))
        if equilibrium_gif_fps <= 0.0:
            raise ValueError(f"equilibrium_gif_fps must be > 0 (got {equilibrium_gif_fps})")
        equilibrium_gif_dpi = int(obj.get("equilibrium_gif_dpi", 100))
        if not (50 <= equilibrium_gif_dpi <= 400):
            raise ValueError(
                f"equilibrium_gif_dpi must be in [50, 400] (got {equilibrium_gif_dpi})"
            )
        export_torax_geometry = bool(obj.get("export_torax_geometry", False))
        torax_geometry_export_authority_path = (
            str(obj["torax_geometry_export_authority_path"])
            if obj.get("torax_geometry_export_authority_path")
            else None
        )
        if export_torax_geometry and not torax_geometry_export_authority_path:
            raise ValueError(
                "export_torax_geometry=true requires torax_geometry_export_authority_path "
                "(ADR-001 fail-closed)"
            )
        compare_efit_archive = bool(obj.get("compare_efit_archive", False))
        efit_compare_authority_path = (
            str(obj["efit_compare_authority_path"])
            if obj.get("efit_compare_authority_path")
            else None
        )
        if compare_efit_archive and not efit_compare_authority_path:
            raise ValueError(
                "compare_efit_archive=true requires efit_compare_authority_path "
                "(ADR-002 fail-closed)"
            )
        execute_planner = bool(obj.get("execute_planner", False))
        planner_authority_path = (
            str(obj["planner_authority_path"]) if obj.get("planner_authority_path") else None
        )
        plasma_scalars_authority_path = (
            str(obj["plasma_scalars_authority_path"])
            if obj.get("plasma_scalars_authority_path")
            else None
        )
        coil_limits_authority_path = (
            str(obj["coil_limits_authority_path"]) if obj.get("coil_limits_authority_path") else None
        )
        circuit_dynamics_authority_path = (
            str(obj["circuit_dynamics_authority_path"])
            if obj.get("circuit_dynamics_authority_path")
            else None
        )
        if execute_planner and not planner_authority_path:
            raise ValueError(
                "execute_planner=true requires planner_authority_path (ADR-004 fail-closed)"
            )
        if execute_planner and not coil_limits_authority_path:
            raise ValueError(
                "execute_planner=true requires coil_limits_authority_path "
                "(ADR-004 hard gate — never invent Imax/Vmax)"
            )
        if execute_evolutive_from_plan and not execute_planner:
            raise ValueError(
                "execute_evolutive_from_plan=true requires execute_planner=true "
                "(planned_voltages from 07_planner)"
            )
        execute_gsfit = bool(obj.get("execute_gsfit", False))
        gsfit_authority_path = (
            str(obj["gsfit_authority_path"]) if obj.get("gsfit_authority_path") else None
        )
        if execute_gsfit and not gsfit_authority_path:
            raise ValueError(
                "execute_gsfit=true requires gsfit_authority_path (ADR-006 fail-closed)"
            )
        # Ensure equilibrium group is downloaded when EFIT compare is enabled
        if compare_efit_archive and "equilibrium" not in optional_groups:
            optional_groups = list(optional_groups) + ["equilibrium"]
        raw_timeout = obj.get("freegsnke_script_timeout_s", 3600.0)
        if raw_timeout is None:
            freegsnke_script_timeout_s: Optional[float] = None
        else:
            freegsnke_script_timeout_s = float(raw_timeout)
            if freegsnke_script_timeout_s <= 0.0:
                raise ValueError(
                    f"freegsnke_script_timeout_s must be > 0 or null (got {freegsnke_script_timeout_s})"
                )

        s3_layout_patterns = list(obj.get("s3_layout_patterns", [
            "{prefix}/{group}/shot_{shot}.zarr",
            "{prefix}/shot_{shot}/{group}.zarr",
            "{prefix}/shot_{shot}_{group}.zarr",
        ]))

        return AppConfig(
            mastapp_base_url=mastapp_base_url,
            required_groups=required_groups,
            optional_groups=optional_groups,
            level2_s3_prefix=level2_s3_prefix,
            s5cmd_path=s5cmd_path,
            s3_endpoint_url=s3_endpoint_url,
            s3_no_sign_request=s3_no_sign_request,
            s5cmd_timeout_s=s5cmd_timeout_s,
            runs_dir=runs_dir,
            cache_dir=cache_dir,
            formed_plasma_frac=formed_plasma_frac,
            s3_layout_patterns=s3_layout_patterns,
            allow_missing_geometry=allow_missing_geometry,
            execute_freegsnke=execute_freegsnke,
            freegsnke_run_mode=freegsnke_run_mode,
            freegsnke_python=freegsnke_python,
            diagnostics_compare=diagnostics_compare,
            diagnostic_contracts_path=diagnostic_contracts_path,
            diagnostic_calibration_path=diagnostic_calibration_path,
            coil_map_path=coil_map_path,
            voltage_map_path=voltage_map_path,
            evolutive_authority_path=evolutive_authority_path,
            passive_resistivity_path=passive_resistivity_path,
            enable_contract_metrics=enable_contract_metrics,
            enable_experimental_data=enable_experimental_data,
            experimental_data_plots=experimental_data_plots,
            experimental_data_include_l1=experimental_data_include_l1,
            experimental_data_include_l3=experimental_data_include_l3,
            execute_evolutive=execute_evolutive,
            execute_evolutive_from_plan=execute_evolutive_from_plan,
            machine_authority_dir=machine_authority_dir,
            require_machine_authority=require_machine_authority,
            rebuild_machine_authority=rebuild_machine_authority,
            provenance_hash_data=provenance_hash_data,
            allow_cache_reuse=allow_cache_reuse,
            batch_abort_on_failure=batch_abort_on_failure,
            enable_shot_suitability_gate=enable_shot_suitability_gate,
            window_end_policy=window_end_policy,
            window_end_ip_frac=window_end_ip_frac,
            metrics_n_times=metrics_n_times,
            write_equilibrium_gifs=write_equilibrium_gifs,
            write_eq_frames=write_eq_frames,
            equilibrium_gif_fps=equilibrium_gif_fps,
            equilibrium_gif_dpi=equilibrium_gif_dpi,
            export_torax_geometry=export_torax_geometry,
            torax_geometry_export_authority_path=torax_geometry_export_authority_path,
            compare_efit_archive=compare_efit_archive,
            efit_compare_authority_path=efit_compare_authority_path,
            execute_planner=execute_planner,
            planner_authority_path=planner_authority_path,
            plasma_scalars_authority_path=plasma_scalars_authority_path,
            coil_limits_authority_path=coil_limits_authority_path,
            circuit_dynamics_authority_path=circuit_dynamics_authority_path,
            profile_trajectory_authority_path=profile_trajectory_authority_path,
            build_profile_trajectory=build_profile_trajectory,
            shape_targets_authority_path=shape_targets_authority_path,
            build_shape_targets=build_shape_targets,
            execute_gsfit=execute_gsfit,
            gsfit_authority_path=gsfit_authority_path,
            freegsnke_script_timeout_s=freegsnke_script_timeout_s,
        )


def run_dir_for_shot(cfg: "AppConfig", shot: int) -> Path:
    """Single source of truth for the user-facing run folder layout (SHOT/<N>)."""
    return Path(cfg.runs_dir) / str(int(shot))


def cache_dir_for_shot(cfg: "AppConfig", shot: int) -> Path:
    """Per-shot download cache folder (data_cache/shot_<N>); layout lives in util.shot_cache_dir."""
    from .util import shot_cache_dir

    return shot_cache_dir(Path(cfg.cache_dir), int(shot))
