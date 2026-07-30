"""Tests for Inverse shape honesty (GS converge ≠ DN success)."""

from __future__ import annotations

from pathlib import Path

from mast_freegsnke.inverse_shape_honesty import score_inverse_shape

REPO = Path(__file__).resolve().parents[1]


def test_score_inverse_shape_dn_missing_x() -> None:
    class _Eq:
        R = [[0.5, 1.0], [0.5, 1.0]]
        Z = [[-1.0, -1.0], [1.0, 1.0]]

        def psi(self):
            return [[0.0, 0.1], [0.0, 0.1]]

    # Monkeypatch critical finder via score path — use a stub by patching module.
    import mast_freegsnke.inverse_shape_honesty as m

    def _fake_crit(eq, *, ip):
        return {
            "ok": True,
            "n_opt": 1,
            "n_xpt": 1,
            "opt": [[0.9, 0.0, 0.2]],
            "xpt": [[0.55, 1.1, 0.05]],
            "psi_axis": 0.2,
            "psi_bndry": 0.05,
            "error": None,
        }

    m.critical_points_from_total_psi = _fake_crit  # type: ignore[assignment]
    nulls = [[0.56, 0.91, 0.54], [-1.19, 0.0, 1.16]]
    audit = score_inverse_shape(
        eq=_Eq(),
        null_points=nulls,
        ip=1e6,
        constrain_loss_final=0.05,
        null_topology="double_null",
    )
    assert audit["dn_claimed"] is True
    assert audit["dn_x_count_ok"] is False
    assert audit["shape_status"] == "dn_missing_xpoints"


def test_score_inverse_shape_unverified_on_high_loss() -> None:
    import mast_freegsnke.inverse_shape_honesty as m

    def _fake_crit(eq, *, ip):
        return {
            "ok": True,
            "n_opt": 1,
            "n_xpt": 2,
            "opt": [[0.91, 0.0, 0.2]],
            "xpt": [[0.56, -1.18, 0.05], [0.54, 1.16, 0.05]],
            "psi_axis": 0.2,
            "psi_bndry": 0.05,
            "error": None,
        }

    m.critical_points_from_total_psi = _fake_crit  # type: ignore[assignment]

    class _Eq:
        pass

    audit = score_inverse_shape(
        eq=_Eq(),
        null_points=[[0.56, 0.91, 0.54], [-1.18, 0.0, 1.16]],
        ip=1e6,
        constrain_loss_final=0.05,
        null_topology="double_null",
    )
    assert audit["dn_x_count_ok"] is True
    assert audit["shape_status"] == "gs_converged_shape_unverified"


def test_inverse_template_has_shape_audit_and_curated_default() -> None:
    tpl = (REPO / "templates" / "inverse_run.py.tpl").read_text(encoding="utf-8")
    assert "score_inverse_shape" in tpl
    assert "gs_converged_shape_unverified" in tpl
    assert "constrain_loss_final" in tpl
    assert 'plot_style", "curated"' in tpl or "plot_style', 'curated'" in tpl
    assert "dump_lcfs" in tpl
