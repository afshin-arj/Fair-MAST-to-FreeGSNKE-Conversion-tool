"""P0/P1/P2 planner audit follow-ups (v11.16)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mast_freegsnke.classic_mast_machine import parallelogram_vertices
from mast_freegsnke.config import AppConfig
from mast_freegsnke.evolutive_from_plan import prepare_plan_voltages_csv

REPO = Path(__file__).resolve().parents[1]
SHOT_CACHE = REPO / "data_cache" / "shot_30201"


def test_parallelogram_axis_aligned() -> None:
    R, Z = parallelogram_vertices(1.0, 0.0, 0.2, 0.4, 0.0, 90.0)
    assert len(R) == 4 and len(Z) == 4
    assert pytest.approx(min(R)) == 0.9
    assert pytest.approx(max(R)) == 1.1
    assert pytest.approx(min(Z)) == -0.2
    assert pytest.approx(max(Z)) == 0.2


def test_prepare_plan_voltages_aligns_columns(tmp_path: Path) -> None:
    run = tmp_path / "SHOT" / "1"
    inputs = run / "inputs"
    (run / "07_planner").mkdir(parents=True)
    inputs.mkdir(parents=True)
    t = np.linspace(0.1, 0.3, 5)
    pd.DataFrame(
        {"time": t, "Solenoid": t * 0 + 10.0, "P4": t * 0 + 2.0}
    ).to_csv(run / "07_planner" / "planned_voltages.csv", index=False)
    pd.DataFrame(
        {
            "time": t,
            "Solenoid": t * 0 + 1.0,
            "P4": t * 0 + 1.0,
            "D1": t * 0 + 99.0,
        }
    ).to_csv(inputs / "pf_voltages.csv", index=False)
    dest = prepare_plan_voltages_csv(run_dir=run, inputs_dir=inputs)
    df = pd.read_csv(dest)
    assert list(df.columns) == ["time", "Solenoid", "P4", "D1"]
    assert float(df["Solenoid"].iloc[0]) == pytest.approx(10.0)
    assert float(df["D1"].iloc[0]) == pytest.approx(99.0)


def test_execute_evolutive_from_plan_default_on() -> None:
    cfg = AppConfig.load(REPO / "configs" / "default.json")
    assert cfg.execute_evolutive_from_plan is True


def test_execute_evolutive_from_plan_requires_planner(tmp_path: Path) -> None:
    src = json.loads((REPO / "configs" / "default.json").read_text(encoding="utf-8"))
    src["execute_planner"] = False
    src["execute_evolutive_from_plan"] = True
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(src), encoding="utf-8")
    with pytest.raises(ValueError, match="execute_planner"):
        AppConfig.load(p)


@pytest.mark.skipif(
    not (SHOT_CACHE / "pf_passive.zarr").exists(),
    reason="data_cache/shot_30201/pf_passive.zarr not present",
)
def test_build_passives_when_rho_cited() -> None:
    from mast_freegsnke.classic_mast_machine import build_passive_coils_from_pf_passive

    passives, note = build_passive_coils_from_pf_passive(
        SHOT_CACHE,
        components={
            "vertw": {
                "resistivity_ohm_m": 7.1e-7,
                "source": "test-only citation fixture (not production)",
            }
        },
    )
    assert len(passives) >= 1
    assert all(p["resistivity"] == pytest.approx(7.1e-7) for p in passives)
    assert "vertw" in note["geometry_components_used"]
    assert passives[0]["source"].startswith("test-only")
