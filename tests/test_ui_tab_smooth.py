"""UI tab-switch smoothness helpers (no layout changes)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from mast_freegsnke.evolutive_from_plan import score_evolutive_ip_at
from mast_freegsnke_ui import artifacts as art
from mast_freegsnke_ui import app as ui_app


def test_tab_body_cache_roundtrip() -> None:
    ui_app._tab_body_cache.clear()
    ui_app._tab_body_cache_put("k1", {"body": 1})
    assert ui_app._tab_body_cache_get("k1") == {"body": 1}
    assert ui_app._tab_body_cache_get("missing") is None
    # Eviction keeps newest
    for i in range(ui_app._TAB_BODY_CACHE_MAX + 5):
        ui_app._tab_body_cache_put(f"x{i}", i)
    assert ui_app._tab_body_cache_get("k1") is None
    assert ui_app._tab_body_cache_get(f"x{ui_app._TAB_BODY_CACHE_MAX + 4}") is not None


def test_score_evolutive_prefers_existing_residual_csv(tmp_path: Path) -> None:
    evo = tmp_path / "03_reconstruction" / "evolutive"
    evo.mkdir(parents=True)
    pd.DataFrame(
        {
            "t_abs": [0.2, 0.3, 0.4],
            "Ip_evolutive": [1.0, 1.0, 1.0],
            "Ip_measured": [2.0, 2.0, 2.0],
            "residual_A": [-1.0, -1.0, -1.0],
        }
    ).to_csv(evo / "ip_residual.csv", index=False)
    # No history.csv — must succeed from residual CSV alone.
    rep = score_evolutive_ip_at(tmp_path, evolutive_relpath="03_reconstruction/evolutive")
    assert rep["ok"] is True
    assert rep.get("from_cached_csv") is True
    assert rep["rms_A"] == pytest.approx(1.0)


def test_efit_plot_paths_prefers_flat_over_deep_walk(tmp_path: Path) -> None:
    plots = tmp_path / "04_efit_compare" / "plots"
    frames = plots / "side_by_side_frames"
    frames.mkdir(parents=True)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (plots / "freegsnke_efit_side_by_side.gif").write_bytes(png)
    (plots / "efit_psi.png").write_bytes(png)
    for i in range(20):
        (frames / f"sbs_{i:03d}.png").write_bytes(png)
    found = art.efit_plot_paths(tmp_path)
    names = {p.name for p in found}
    assert "freegsnke_efit_side_by_side.gif" in names
    assert "efit_psi.png" in names
    # Nested frames are capped (≤8), not a full 20-file walk.
    assert sum(1 for n in names if n.startswith("sbs_")) <= 8


def test_results_fingerprint_includes_planner_efit(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    (run / "01_summary").mkdir(parents=True)
    (run / "07_planner").mkdir(parents=True)
    (run / "01_summary" / "SUMMARY.json").write_text("{}", encoding="utf-8")
    fp1 = art.results_fingerprint(run)
    (run / "07_planner" / "PLANNER.json").write_text('{"ok":true}\n', encoding="utf-8")
    fp2 = art.results_fingerprint(run)
    assert fp1 != fp2
