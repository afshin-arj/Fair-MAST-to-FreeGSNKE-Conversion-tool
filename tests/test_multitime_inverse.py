"""v10.5.0: full-inverse multi-time synthetic + hard timeout caps."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from mast_freegsnke.config import AppConfig
from mast_freegsnke.execution_authority import (
    MultiTimeSolveSpec,
    load_execution_authority_bundle,
    write_execution_authority,
)
from mast_freegsnke.freegsnke_runner import FreeGSNKERunner
from mast_freegsnke.generate import ScriptGenerator


REPO = Path(__file__).resolve().parents[1]


def test_multitime_solve_spec_defaults_and_validation() -> None:
    spec = MultiTimeSolveSpec()
    spec.validate()
    assert spec.preferred_mode == "full_inverse"
    assert spec.fresh_constrain_per_time is True
    assert spec.fallback_mode == "forward_gs"
    assert spec.max_solving_iterations == 50
    assert spec.per_time_timeout_s == 180.0
    assert spec.continuation is True

    with pytest.raises(ValueError, match="fresh_constrain_per_time"):
        MultiTimeSolveSpec(fresh_constrain_per_time=False).validate()
    with pytest.raises(ValueError, match="preferred_mode"):
        MultiTimeSolveSpec(preferred_mode="invented").validate()
    with pytest.raises(ValueError, match="fallback_mode"):
        MultiTimeSolveSpec(fallback_mode="fabricate").validate()
    with pytest.raises(ValueError, match="max_solving_iterations"):
        MultiTimeSolveSpec(max_solving_iterations=0).validate()
    with pytest.raises(ValueError, match="per_time_timeout_s"):
        MultiTimeSolveSpec(per_time_timeout_s=0.0).validate()


def test_execution_authority_writes_multitime_solver_knobs(tmp_path: Path) -> None:
    root = write_execution_authority(tmp_path, metrics_n_times=5)
    bundle = load_execution_authority_bundle(root / "execution_authority_bundle.json")
    assert bundle.authority_version == "11.25.0"
    assert bundle.solver.multitime.preferred_mode == "full_inverse"
    assert bundle.solver.multitime.fresh_constrain_per_time is True
    assert bundle.solver.multitime.max_solving_iterations == 50
    assert bundle.solver.multitime.per_time_timeout_s == 180.0
    assert bundle.solver.inverse_shape_acceptance.enabled is True
    assert bundle.solver.inverse_shape_acceptance.on_fail == "label_only"
    assert bundle.solver.inverse_shape_retry.max_retries == 1
    assert bundle.solver.forward_profile_source == "profile_trajectory_if_ok"
    assert bundle.solver.forward_ic_psi == "inverse_dump"

    raw = json.loads((root / "solver_spec.json").read_text())
    assert "multitime" in raw
    assert raw["multitime"]["preferred_mode"] == "full_inverse"
    assert "inverse_shape_acceptance" in raw
    assert "inverse_shape_retry" in raw
    assert raw["forward_profile_source"] == "profile_trajectory_if_ok"
    assert raw["forward_ic_psi"] == "inverse_dump"


def test_execution_authority_loads_legacy_bundle_without_forward_profile_source(
    tmp_path: Path,
) -> None:
    root = write_execution_authority(tmp_path, metrics_n_times=3)
    bundle_path = root / "execution_authority_bundle.json"
    obj = json.loads(bundle_path.read_text())
    del obj["solver"]["forward_profile_source"]
    del obj["solver"]["forward_ic_psi"]
    bundle_path.write_text(json.dumps(obj, indent=2) + "\n")
    loaded = load_execution_authority_bundle(bundle_path)
    assert loaded.solver.forward_profile_source == "profile_trajectory_if_ok"
    assert loaded.solver.forward_ic_psi == "inverse_dump"


def test_execution_authority_loads_legacy_bundle_without_shape_gate(tmp_path: Path) -> None:
    """Bundles without shape gate keys get safe defaults (not invent thresholds)."""
    root = write_execution_authority(tmp_path, metrics_n_times=3)
    bundle_path = root / "execution_authority_bundle.json"
    obj = json.loads(bundle_path.read_text())
    del obj["solver"]["inverse_shape_acceptance"]
    del obj["solver"]["inverse_shape_retry"]
    bundle_path.write_text(json.dumps(obj, indent=2) + "\n")

    loaded = load_execution_authority_bundle(bundle_path)
    assert loaded.solver.inverse_shape_acceptance.enabled is True
    assert loaded.solver.inverse_shape_retry.max_retries == 1


def test_execution_authority_loads_legacy_bundle_without_multitime(tmp_path: Path) -> None:
    """Older 10.4.0 bundles without solver.multitime get safe defaults."""
    root = write_execution_authority(tmp_path, metrics_n_times=3)
    bundle_path = root / "execution_authority_bundle.json"
    obj = json.loads(bundle_path.read_text())
    del obj["solver"]["multitime"]
    obj["authority_version"] = "10.4.0"
    bundle_path.write_text(json.dumps(obj, indent=2) + "\n")

    loaded = load_execution_authority_bundle(bundle_path)
    assert loaded.solver.multitime.preferred_mode == "full_inverse"
    assert loaded.solver.multitime.fresh_constrain_per_time is True


def test_inverse_template_uses_full_inverse_multitime_path() -> None:
    tpl = (REPO / "templates" / "inverse_run.py.tpl").read_text(encoding="utf-8")
    assert "preferred_mode" in tpl
    assert "full_inverse" in tpl
    assert "fresh_constrain_per_time" in tpl
    assert "per_time_timeout_s" in tpl
    assert "max_solving_iterations" in tpl
    assert "_solve_one_sample_inplace" in tpl
    assert "forward_gs_at_measured_pf_ip" in tpl  # fallback / overall mode label
    # Must not soft-pedal the stall root cause out of the note.
    assert "fastcrit" in tpl or "new_residual_flag" in tpl
    # Child-process hard kill for hung FreeGSNKE residual-resize loops.
    assert "_multitime_solve_worker" in tpl
    assert "multiprocessing" in tpl
    assert "proc.terminate()" in tpl or "terminate()" in tpl
    assert "_solve_one_sample(" in tpl
    # t0 inverse must use hard kill + max_iter (shot 30202 uncapped hang).
    assert "[..] t0" in tpl
    assert "restore_optimized_currents" in tpl
    assert "t0_solve_mode" in tpl
    assert "SystemExit(2)" in tpl
    # Cold t0 Inverse can fail while continuation works (30201); retry after forward_gs seed.
    assert "full_inverse retry after forward_gs seed" in tpl
    assert "attach_profiles_after_restore" in tpl
    assert "_boundary_for_time" in tpl
    assert "boundary_dict_at_time" in tpl
    assert "coil_current_limits" in tpl
    assert "score_inverse_shape" in tpl
    assert "dump_lcfs" in tpl
    assert "_apply_shape_gate_and_retry" in tpl
    assert "inverse_shape_retry" in tpl
    assert "inverse_result.json" in tpl


def test_rendered_inverse_script_keeps_multitime_tokens(tmp_path: Path) -> None:
    gen = ScriptGenerator(templates_dir=REPO / "templates")
    gen.generate(tmp_path, machine_dir=tmp_path / "machine", formed_frac=0.8)
    inv = (tmp_path / "inverse_run.py").read_text(encoding="utf-8")
    assert "__MACHINE_DIR_REPR__" not in inv
    assert "__FORMED_FRAC__" not in inv
    assert "full_inverse" in inv
    assert "per_time_timeout_s" in inv


def test_runner_kills_script_on_timeout(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    script = run_dir / "inverse_run.py"
    script.write_text("import time\ntime.sleep(30)\nprint('should_not_finish')\n")

    r = FreeGSNKERunner(timeout_s=1.0).run_script(script, run_dir=run_dir, label="inverse")
    assert r.ok is False
    assert r.timed_out is True
    assert r.returncode == 124
    assert r.error_hint == "freegsnke_script_timeout"
    assert r.duration_s < 10.0
    stderr = (run_dir / r.stderr_path).read_text()
    assert "TIMEOUT" in stderr


def test_runner_does_not_hang_on_orphaned_grandchild(tmp_path: Path) -> None:
    """Regression: grandchild holding inherited handles must not block the runner.

    On Windows, multitime spawn children can outlive the script parent. Writing
    logs to files (not PIPE) keeps wait() from depending on grandchild EOF.
    """
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    marker = run_dir / "grandchild.pid"
    script = run_dir / "inverse_run.py"
    script.write_text(
        "import subprocess, sys, time\n"
        f"marker = {str(marker)!r}\n"
        "subprocess.Popen(\n"
        "    [sys.executable, '-c',\n"
        "     (\"open(%r, 'w').write(str(__import__('os').getpid())); \"\n"
        "      \"__import__('time').sleep(60)\") % (marker,)],\n"
        "    close_fds=False,\n"
        ")\n"
        "time.sleep(0.4)\n"
        "print('parent_exiting', flush=True)\n"
        "raise SystemExit(0)\n",
        encoding="utf-8",
    )
    r = FreeGSNKERunner(timeout_s=10.0).run_script(script, run_dir=run_dir, label="inverse")
    assert r.ok is True, (
        r.returncode,
        r.error_hint,
        (run_dir / "logs" / "inverse.stderr.txt").read_text(errors="replace")[:500],
    )
    assert r.duration_s < 8.0
    if marker.exists():
        try:
            import subprocess

            gpid = int(marker.read_text().strip())
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(gpid)],
                    capture_output=True,
                    check=False,
                )
            else:
                os.kill(gpid, 9)
        except Exception:
            pass


def test_runner_evolutive_per_step_timeout_hint(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    script = run_dir / "evolutive_run.py"
    script.write_text(
        "import os\n"
        "print('[TIMEOUT] evolutive nlstepper step 10 exceeded "
        "per_step_timeout_s=180.0 - process hard-killed')\n"
        "os._exit(124)\n",
        encoding="utf-8",
    )
    r = FreeGSNKERunner(timeout_s=30.0).run_script(script, run_dir=run_dir, label="evolutive")
    assert r.ok is False
    assert r.timed_out is False
    assert r.returncode == 124
    assert r.error_hint == "evolutive_per_step_timeout"


def test_evolutive_template_has_ip_collapse_abort() -> None:
    tpl = (REPO / "templates" / "evolutive_run.py.tpl").read_text(encoding="utf-8")
    assert "abort_when_ip_below_measured_frac" in tpl
    assert "[ABORT] evolutive Ip collapsed" in tpl
    assert "early_stop" in tpl
    assert "clamp_ip_to_measured" in tpl
    assert "ic_coil_currents" in tpl
    assert "inverse_dump" in tpl
    assert "n_passive" in tpl
    assert "abort_when_axis_drift_m" in tpl
    assert "[ABORT] evolutive axis drift" in tpl
    assert 'profiles_parameters["Ip"]' in tpl or "profiles_parameters[\"Ip\"]" in tpl


def test_forward_template_plot_honesty_and_profile_source() -> None:
    tpl = (REPO / "templates" / "forward_run.py.tpl").read_text(encoding="utf-8")
    assert "save_equilibrium_png" in tpl
    assert "attach_profiles_after_restore" in tpl
    assert "measured-PF replay" in tpl
    assert "use_inverse_dump_lcfs=False" in tpl
    assert "use_inverse_targets=False" in tpl
    assert "LCFS (Forward)" in tpl
    assert "forward_profile_source" in tpl
    assert "profile_trajectory_if_ok" in tpl
    assert "forward_ic_psi" in tpl
    assert "_apply_forward_ic_psi" in tpl
    assert "n_converged" in tpl
    assert "n_completed_max_iter" in tpl
    assert "_forward_shape_audit" in tpl
    assert '_plot_style = str(getattr(pres, "plot_style", "curated")' in tpl or 'plot_style", "curated"' in tpl
    # Must not silently default Forward plots to freegsnke_native.
    assert 'plot_style", "freegsnke_native"' not in tpl
    assert "plot_style', 'freegsnke_native'" not in tpl


def test_runner_pins_blas_threads_by_default() -> None:
    r = FreeGSNKERunner(timeout_s=1.0)
    assert r.env.get("OMP_NUM_THREADS") == "1"
    assert r.env.get("MKL_NUM_THREADS") == "1"
    assert r.env.get("OPENBLAS_NUM_THREADS") == "1"


def test_evolutive_partial_history_n(tmp_path: Path) -> None:
    from mast_freegsnke.freegsnke_runner import evolutive_partial_history_n

    run_dir = tmp_path / "30202"
    evo = run_dir / "evolutive"
    evo.mkdir(parents=True)
    (evo / "history.csv").write_text(
        "t_abs,Ip,step_ok\n0.1,1e5,True\n0.12,9e4,True\n0.14,nan,False\n",
        encoding="utf-8",
    )
    assert evolutive_partial_history_n(run_dir) == 2


def test_inverse_template_uses_timer_hard_kill() -> None:
    tpl = (REPO / "templates" / "inverse_run.py.tpl").read_text(encoding="utf-8")
    assert "threading.Timer" in tpl or "_threading.Timer" in tpl
    assert "taskkill" in tpl
    assert "per_time_timeout_s" in tpl


def test_evolutive_template_watches_ic_static_gs() -> None:
    tpl = (REPO / "templates" / "evolutive_run.py.tpl").read_text(encoding="utf-8")
    assert 'label="ic_static_gs"' in tpl or "label='ic_static_gs'" in tpl
    assert "Static GS solve for evolutive IC" in tpl
    # IC solve must cap iterations — omitting max_solving_iterations hangs freegs4e.
    ic_block = tpl.split("Static GS solve for evolutive IC", 1)[1].split("nl_kwargs", 1)[0]
    assert "max_solving_iterations=max_iter" in ic_block


def test_runner_success_untimed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    script = run_dir / "forward_run.py"
    script.write_text("print('ok')\n")
    r = FreeGSNKERunner(timeout_s=30.0).run_script(script, run_dir=run_dir, label="forward")
    assert r.ok is True
    assert r.timed_out is False
    assert r.error_hint is None


def test_default_config_ships_script_timeout() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.freegsnke_script_timeout_s == 3600.0
    assert cfg.metrics_n_times == 41
    assert cfg.window_end_policy == "ip_peak_then_floor"
    assert cfg.window_end_ip_frac == 0.90


def test_synthetic_times_schema_records_per_time_status(tmp_path: Path) -> None:
    """Metrics embed the richer synthetic_times.json (per-time solve status)."""
    from mast_freegsnke.diagnostic_contracts import resolve_contracts_for_run
    from mast_freegsnke.metrics import compare_from_contracts
    import numpy as np
    import pandas as pd

    run_dir = tmp_path / "run"
    (run_dir / "inputs").mkdir(parents=True)
    (run_dir / "synthetic").mkdir()

    t = np.linspace(0.0, 1.0, 101)
    y = 0.1 + 0.05 * t
    pd.DataFrame({"time": t, "CC03": y}).to_csv(run_dir / "inputs" / "flux_loops.csv", index=False)
    times = [0.2, 0.5, 0.8]
    syn_vals = np.interp(times, t, y)
    pd.DataFrame({"time": times, "FL_CC03": syn_vals}).to_csv(
        run_dir / "synthetic" / "synthetic_fluxloops.csv", index=False
    )
    (run_dir / "synthetic" / "synthetic_times.json").write_text(json.dumps({
        "rule": "linspace_window_inclusive",
        "n_times": 3,
        "t_start": 0.2,
        "t_end": 0.8,
        "times": times,
        "solve_mode": "full_inverse",
        "n_inverse_converged": 3,
        "n_forward_gs_fallback": 0,
        "n_skipped": 0,
        "per_time": [
            {
                "t": float(ti),
                "status": "converged",
                "solve_mode": "full_inverse",
                "iterations": 10,
                "rel_change": 1e-4,
                "duration_s": 1.0,
            }
            for ti in times
        ],
    }))

    contracts_json = tmp_path / "contracts.json"
    contracts_json.write_text(json.dumps({
        "version": "1.0",
        "diagnostics": [{
            "name": "FL_CC03",
            "dtype": "flux_loop",
            "units": "Wb",
            "exp": {"csv": "inputs/flux_loops.csv", "time_col": "time", "value_col": "CC03"},
            "syn": {"csv": "synthetic/synthetic_fluxloops.csv", "time_col": "time", "value_col": "FL_CC03"},
        }],
    }))
    contracts = resolve_contracts_for_run(contracts_json, run_dir)
    met = compare_from_contracts(run_dir, contracts)
    assert met["ok"], met["errors"]
    tb = met["synthetic_timebase"]
    assert tb["solve_mode"] == "full_inverse"
    assert tb["n_inverse_converged"] == 3
    assert len(tb["per_time"]) == 3
    assert all(p["solve_mode"] == "full_inverse" for p in tb["per_time"])
