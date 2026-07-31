"""Science audit + presentation honesty for Inverse shape gate (v11.23.0)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from mast_freegsnke.equilibrium_presentation import plot_equilibrium_curated
from mast_freegsnke.science_audit import inverse_shape_gate_summary
from mast_freegsnke.shot_summary import _KNOWN_LIMITATIONS

REPO = Path(__file__).resolve().parents[1]


def test_plot_equilibrium_curated_open_field_on_by_default() -> None:
    sig = inspect.signature(plot_equilibrium_curated)
    assert sig.parameters["show_open_field"].default is True
    src = inspect.getsource(plot_equilibrium_curated)
    assert "mask_psi_for_structure_safe_contours" in src
    assert "structure-masked" in src or "not through coils" in src


def test_inverse_shape_gate_summary_from_result_json(tmp_path: Path) -> None:
    run = tmp_path / "SHOT" / "1"
    run.mkdir(parents=True)
    (run / "inverse_result.json").write_text(
        json.dumps(
            {
                "status": "gs_converged_shape_unverified",
                "shape_accepted": False,
                "rel_change": 1e-4,
                "constrain_loss_final": 0.02,
                "shape_audit": {
                    "shape_status": "gs_converged_shape_unverified",
                    "shape_accepted": False,
                    "constrain_loss_final": 0.02,
                    "fail_reasons": ["constrain_loss=0.02>0.01"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    syn = run / "synthetic"
    syn.mkdir(parents=True)
    (syn / "synthetic_times.json").write_text(
        json.dumps(
            {
                "solve_mode": "full_inverse",
                "n_times": 2,
                "per_time": [
                    {
                        "t": 0.2,
                        "status": "shape_accepted",
                        "shape_accepted": True,
                        "shape_audit": {
                            "shape_status": "shape_accepted",
                            "shape_accepted": True,
                        },
                    },
                    {
                        "t": 0.3,
                        "status": "gs_converged_shape_unverified",
                        "shape_accepted": False,
                        "shape_audit": {
                            "shape_status": "gs_converged_shape_unverified",
                            "shape_accepted": False,
                        },
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    gate = inverse_shape_gate_summary(run)
    assert gate["available"] is True
    assert gate["t0"]["shape_status"] == "gs_converged_shape_unverified"
    assert gate["n_shape_accepted"] == 1
    assert gate["n_gs_ok_shape_unverified"] == 1
    assert "GS residual" in gate["note"]


def test_known_limitations_mention_gs_vs_shape() -> None:
    blob = " ".join(_KNOWN_LIMITATIONS)
    assert "GS residual" in blob
    assert "open-field" in blob
