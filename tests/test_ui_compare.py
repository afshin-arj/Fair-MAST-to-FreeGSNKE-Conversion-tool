"""Browse-only Compare tab: scorecard deltas + side-by-side panel smoke."""
from __future__ import annotations

import json
from pathlib import Path

from mast_freegsnke_ui import artifacts as art
from mast_freegsnke_ui import panels


_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _mini_shot(run_dir: Path, shot: int, *, rms: float, t0: float, t1: float) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "01_summary").mkdir(exist_ok=True)
    (run_dir / "01_summary" / "SUMMARY.json").write_text(
        json.dumps(
            {
                "shot": shot,
                "status": "success",
                "window": {"t_start": t0, "t_end": t1},
                "modes": {"inverse": "ok", "evolutive": "ok"},
                "blocking_errors": [],
                "science_audit": {"evolutive_ip": {"ok": True, "rms_A": rms}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "manifest.json").write_text(
        json.dumps({"shot": shot, "status": "success", "blocking_errors": [], "stage_log": []})
        + "\n",
        encoding="utf-8",
    )
    metrics_dir = run_dir / "03_reconstruction" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    (metrics_dir / "reconstruction_metrics.json").write_text(
        json.dumps({"ok": True, "n_scored": 2, "n_skipped_all_nan": 0, "per_contract": {}})
        + "\n",
        encoding="utf-8",
    )
    plots = run_dir / "02_measured_data" / "05_plots"
    plots.mkdir(parents=True, exist_ok=True)
    (plots / "01_plasma_ip.png").write_bytes(_PNG)
    (run_dir / "02_measured_data" / "01_plasma").mkdir(parents=True, exist_ok=True)
    (run_dir / "02_measured_data" / "01_plasma" / "ip.csv").write_text(
        "time,ip\n0.1,1e5\n", encoding="utf-8"
    )
    (run_dir / "02_measured_data" / "00_index").mkdir(parents=True, exist_ok=True)
    (run_dir / "02_measured_data" / "00_index" / "catalog.json").write_text(
        json.dumps({"families": {"plasma": {"csv": ["01_plasma/ip.csv"]}}}) + "\n",
        encoding="utf-8",
    )
    pres = run_dir / "03_reconstruction" / "presentation"
    pres.mkdir(parents=True, exist_ok=True)
    (pres / "eq.gif").write_bytes(_PNG)


def test_compare_in_tab_defs() -> None:
    ids = [k for k, _ in panels.TAB_DEFS]
    assert "compare" in ids
    assert ids.index("compare") == ids.index("residuals") + 1
    assert "compare" in panels.TAB_META


def test_compare_scorecard_deltas(tmp_path: Path) -> None:
    a = tmp_path / "30203"
    b = tmp_path / "30204"
    _mini_shot(a, 30203, rms=100.0, t0=0.2, t1=0.4)
    _mini_shot(b, 30204, rms=250.0, t0=0.19, t1=0.41)
    card = art.compare_scorecard(a, b, shot_a=30203, shot_b=30204)
    assert card["a_present"] is True
    assert card["b_present"] is True
    by_key = {r["key"]: r for r in card["rows"]}
    assert by_key["status"]["a"] == "success"
    assert by_key["evolutive_rms_A"]["delta"] == 150.0
    assert abs(float(by_key["t_start"]["delta"]) - (-0.01)) < 1e-9
    assert by_key["modes"]["delta"] is None


def test_compare_scorecard_missing_side(tmp_path: Path) -> None:
    a = tmp_path / "30203"
    _mini_shot(a, 30203, rms=10.0, t0=0.1, t1=0.2)
    card = art.compare_scorecard(a, tmp_path / "missing", shot_a=30203, shot_b=99999)
    assert card["a_present"] is True
    assert card["b_present"] is False
    by_key = {r["key"]: r for r in card["rows"]}
    assert by_key["n_scored"]["a"] == 2
    assert by_key["n_scored"]["b"] is None
    assert by_key["n_scored"]["delta"] is None


def test_pair_paths_by_name(tmp_path: Path) -> None:
    pa = [tmp_path / "a" / "01_plasma_ip.png", tmp_path / "a" / "only_a.png"]
    pb = [tmp_path / "b" / "01_plasma_ip.png", tmp_path / "b" / "only_b.png"]
    for p in pa + pb:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_PNG)
    pairs = art.pair_paths_by_name(pa, pb)
    names = [p["name"] for p in pairs]
    assert names == ["01_plasma_ip.png", "only_a.png", "only_b.png"]
    assert pairs[0]["a"] is not None and pairs[0]["b"] is not None
    assert pairs[1]["b"] is None
    assert pairs[2]["a"] is None


def test_default_compare_pair() -> None:
    a, b = panels.default_compare_pair(30203, [30204, 30203, 30202])
    assert a == 30203
    assert b == 30204
    a2, b2 = panels.default_compare_pair(None, [30201])
    assert a2 == 30201
    assert b2 is None


def test_compare_detail_empty_both(tmp_path: Path) -> None:
    body = panels.compare_detail(tmp_path, None, None, "plasma")
    assert body is not None


def test_compare_detail_and_panel(tmp_path: Path) -> None:
    runs = tmp_path / "SHOT"
    _mini_shot(runs / "30203", 30203, rms=100.0, t0=0.2, t1=0.4)
    _mini_shot(runs / "30204", 30204, rms=200.0, t0=0.2, t1=0.4)
    detail = panels.compare_detail(runs, 30203, 30204, "plasma")
    assert detail is not None
    panel = panels.compare_panel(
        runs,
        library_options=[{"label": "30203", "value": 30203}, {"label": "30204", "value": 30204}],
        shot_a=30203,
        shot_b=30204,
        family="plasma",
    )
    assert panel is not None


def test_fill_one_tab_compare_does_not_require_active_shot() -> None:
    body = panels.fill_one_tab("compare", None, None)
    assert body is not None


def test_compare_same_shot_warns(tmp_path: Path) -> None:
    runs = tmp_path / "SHOT"
    _mini_shot(runs / "30203", 30203, rms=100.0, t0=0.2, t1=0.4)
    detail = panels.compare_detail(runs, 30203, 30203, "plasma")
    text = str(detail)
    assert "same number" in text.lower() or "identical" in text.lower()


def test_compare_missing_side_is_soft(tmp_path: Path) -> None:
    runs = tmp_path / "SHOT"
    _mini_shot(runs / "30203", 30203, rms=100.0, t0=0.2, t1=0.4)
    detail = panels.compare_detail(runs, 30203, 99999, "plasma")
    text = str(detail)
    assert "99999" in text
    assert "browse-only" in text.lower() or "missing" in text.lower()
