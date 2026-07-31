"""Forward presentation honesty + forward_gate SUMMARY (v11.24.0)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from unittest.mock import patch

from mast_freegsnke.equilibrium_presentation import save_equilibrium_png
from mast_freegsnke.science_audit import forward_gate_summary
from mast_freegsnke.shot_summary import _KNOWN_LIMITATIONS

REPO = Path(__file__).resolve().parents[1]


def test_save_equilibrium_png_skips_inverse_dump_when_disabled(tmp_path: Path) -> None:
    sig = inspect.signature(save_equilibrium_png)
    assert sig.parameters["use_inverse_dump_lcfs"].default is True
    assert sig.parameters["use_inverse_targets"].default is True

    class _Eq:
        R = [[0.5, 1.0], [0.5, 1.0]]
        Z = [[-1.0, -1.0], [1.0, 1.0]]
        nx = 2
        ny = 2

        def psi(self):
            return [[0.0, 0.1], [0.0, 0.1]]

    # Avoid real matplotlib/freegsnke: assert loaders are not called when flags False.
    with (
        patch(
            "mast_freegsnke.equilibrium_presentation.load_dump_lcfs",
            side_effect=AssertionError("must not load Inverse dump LCFS"),
        ),
        patch(
            "mast_freegsnke.equilibrium_presentation.load_inverse_null_targets",
            side_effect=AssertionError("must not load Inverse targets"),
        ),
        patch(
            "mast_freegsnke.equilibrium_presentation.plot_equilibrium_curated",
            return_value=None,
        ),
        patch("matplotlib.pyplot.subplots") as subplots,
        patch("matplotlib.pyplot.close"),
        patch("matplotlib.use"),
    ):
        class _Ax:
            def set_title(self, *a, **k):
                pass

            def legend(self, *a, **k):
                pass

        class _Fig:
            def tight_layout(self):
                pass

            def savefig(self, *a, **k):
                pass

        subplots.return_value = (_Fig(), _Ax())
        out = tmp_path / "fwd.png"
        save_equilibrium_png(
            tokamak=None,
            eq=_Eq(),
            out_path=out,
            title="Forward test",
            run_dir=tmp_path,
            use_inverse_dump_lcfs=False,
            use_inverse_targets=False,
            plot_style="curated",
        )


def test_forward_gate_summary_from_times_json(tmp_path: Path) -> None:
    run = tmp_path / "SHOT" / "1"
    pres = run / "presentation"
    pres.mkdir(parents=True)
    (pres / "forward_times.json").write_text(
        json.dumps(
            {
                "n_times": 3,
                "n_ok": 2,
                "n_converged": 1,
                "n_completed_max_iter": 1,
                "n_skipped": 1,
                "solve_mode": "forward_gs",
                "ic_psi_used": "inverse_dump",
                "profile_source_requested": "profile_trajectory_if_ok",
                "profile_sources_used": ["profile_trajectory"],
                "note": "measured PF/Ip",
                "per_time": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run / "forward_equilibrium.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    gate = forward_gate_summary(run)
    assert gate["available"] is True
    assert gate["n_ok"] == 2
    assert gate["n_converged"] == 1
    assert gate["n_completed_max_iter"] == 1
    assert gate["ic_psi_used"] == "inverse_dump"
    assert gate["profile_source_requested"] == "profile_trajectory_if_ok"
    assert gate["forward_png_present"] is True
    assert "Inverse dump LCFS" in gate["note"] or "live Forward LCFS" in gate["note"]


def test_known_limitations_mention_forward_lcfs() -> None:
    blob = " ".join(_KNOWN_LIMITATIONS)
    assert "live Forward LCFS" in blob or "Forward dump LCFS" in blob or "never Inverse dump LCFS" in blob
    assert "forward_profile_source" in blob or "measured PF" in blob
