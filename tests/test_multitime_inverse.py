"""v10.5.0: full-inverse multi-time synthetic + hard timeout caps."""
from __future__ import annotations

import json
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
    assert bundle.authority_version == "10.5.0"
    assert bundle.solver.multitime.preferred_mode == "full_inverse"
    assert bundle.solver.multitime.fresh_constrain_per_time is True
    assert bundle.solver.multitime.max_solving_iterations == 50
    assert bundle.solver.multitime.per_time_timeout_s == 180.0

    raw = json.loads((root / "solver_spec.json").read_text())
    assert "multitime" in raw
    assert raw["multitime"]["preferred_mode"] == "full_inverse"


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
    # Child-process spawn path was retired (Windows rebuild overhead).
    assert "_multitime_solve_worker" not in tpl
    assert "multiprocessing" not in tpl


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
    assert cfg.freegsnke_script_timeout_s == 1200.0
    assert cfg.metrics_n_times == 5


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
