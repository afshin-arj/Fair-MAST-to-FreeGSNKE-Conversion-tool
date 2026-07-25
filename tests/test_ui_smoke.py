"""UI artifact loaders + run-manager smoke (no FreeGSNKE)."""
from __future__ import annotations

import json
import os
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mast_freegsnke_ui import artifacts as art
from mast_freegsnke_ui.run_manager import RunManager

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _fixture_shot(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "01_summary").mkdir(exist_ok=True)
    (run_dir / "01_summary" / "SUMMARY.json").write_text(
        json.dumps(
            {
                "shot": 30201,
                "status": "success",
                "window": {"t_start": 0.1, "t_end": 0.3},
                "modes": {"inverse": "ok", "forward": "ok"},
                "blocking_errors": [],
                "science_audit": {"evolutive_ip": {"ok": True, "rms_A": 1.2}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "01_summary" / "SUMMARY.md").write_text("# Shot 30201\n\nOK.\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps({"shot": 30201, "status": "success", "blocking_errors": [], "stage_log": []})
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "progress.json").write_text(
        json.dumps(
            {
                "shot": 30201,
                "status": "success",
                "current_stage": "shot_layout",
                "stage_log": [
                    {"stage": "download", "ok": True},
                    {"stage": "shot_layout", "ok": True},
                ],
                "blocking_errors": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    metrics_dir = run_dir / "03_reconstruction" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    (metrics_dir / "reconstruction_metrics.json").write_text(
        json.dumps(
            {
                "ok": True,
                "n_scored": 1,
                "n_skipped_all_nan": 0,
                "per_contract": {"fl_01": {"rms": 0.01, "mae": 0.02, "max_abs": 0.03, "n": 10}},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (metrics_dir / "residual_fl_01.csv").write_text(
        "time,exp,syn,residual\n0.1,1.0,1.1,-0.1\n0.2,1.0,0.9,0.1\n",
        encoding="utf-8",
    )
    plots = run_dir / "02_measured_data" / "05_plots"
    plots.mkdir(parents=True, exist_ok=True)
    (plots / "01_plasma_ip.png").write_bytes(_PNG)
    plasma = run_dir / "02_measured_data" / "01_plasma"
    plasma.mkdir(parents=True, exist_ok=True)
    (plasma / "ip.csv").write_text("time,ip\n0.1,1.0e5\n0.2,1.1e5\n", encoding="utf-8")
    (run_dir / "02_measured_data" / "00_index").mkdir(parents=True, exist_ok=True)
    (run_dir / "02_measured_data" / "00_index" / "catalog.json").write_text(
        json.dumps(
            {
                "shot": 30201,
                "window_s": [0.1, 0.3],
                "families": {"ip": {"path": "02_measured_data/01_plasma/ip.csv", "columns": ["time", "ip"]}},
                "plots": ["05_plots/01_plasma_ip.png"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    key_plots = run_dir / "report" / "key_plots"
    key_plots.mkdir(parents=True, exist_ok=True)
    (key_plots / "fl_01_residual.png").write_bytes(_PNG)
    auth = run_dir / "06_authorities" / "contracts"
    auth.mkdir(parents=True, exist_ok=True)
    (auth / "voltage_map.sha256.json").write_text(
        json.dumps({"sha256": "abcd" * 16}) + "\n", encoding="utf-8"
    )
    efit = run_dir / "04_efit_compare"
    efit.mkdir(exist_ok=True)
    (efit / "COMPARE.json").write_text(
        json.dumps({"ok": True, "label": "FAIR-MAST EFIT++ archive"}) + "\n",
        encoding="utf-8",
    )
    (efit / "plots").mkdir(exist_ok=True)
    (efit / "plots" / "lcfs_compare.png").write_bytes(_PNG)
    pres = run_dir / "03_reconstruction" / "presentation"
    pres.mkdir(parents=True, exist_ok=True)
    (pres / "inverse_equilibria.gif").write_bytes(b"GIF89a")


def test_list_and_overview(tmp_path: Path) -> None:
    runs = tmp_path / "SHOT"
    shot_dir = runs / "30201"
    _fixture_shot(shot_dir)
    assert art.list_shot_dirs(runs) == [30201]
    text = art.overview_text(shot_dir)
    assert "30201" in text
    assert "success" in text
    assert "[0.1, 0.3]" in text
    k = art.overview_kpis(shot_dir)
    assert k["n_scored"] == 1
    assert k["efit_ok"] is True


def test_metrics_auth_catalog_zip(tmp_path: Path) -> None:
    shot_dir = tmp_path / "30201"
    _fixture_shot(shot_dir)
    metrics = art.load_metrics(shot_dir)
    rows = art.metrics_table_rows(metrics)
    assert rows and rows[0]["contract"] == "fl_01"
    assert art.residual_csv_paths(shot_dir)
    assert art.measured_plot_paths(shot_dir)
    assert art.residual_plot_paths(shot_dir)
    assert art.efit_plot_paths(shot_dir)
    assert art.gif_paths(shot_dir)
    uri = art.file_to_data_uri(art.measured_plot_paths(shot_dir)[0])
    assert uri and uri.startswith("data:image/png;base64,")
    snap = art.authority_snapshot(shot_dir)
    assert any(i["label"] == "voltage_map.sha256" for i in snap["items"])
    assert art.load_efit_compare(shot_dir)["ok"] is True

    cat = art.catalog_downloadables(shot_dir)
    assert any(i["rel"].endswith("01_plasma_ip.png") for i in cat)
    assert any(i["kind"] == "csv" for i in cat)

    assert art.safe_resolve_under(shot_dir, "../secrets.txt") is None
    assert art.safe_resolve_under(shot_dir, "manifest.json") is not None

    raw = art.build_run_zip_bytes(shot_dir)
    with zipfile.ZipFile(BytesIO(raw)) as zf:
        names = zf.namelist()
    assert any(n.endswith("manifest.json") for n in names)
    assert any(n.endswith("01_plasma_ip.png") for n in names)


def test_plot_urls_are_servable(tmp_path: Path) -> None:
    shot_dir = tmp_path / "30201"
    _fixture_shot(shot_dir)
    for finder in (art.measured_plot_paths, art.residual_plot_paths, art.efit_plot_paths, art.gif_paths):
        paths = finder(shot_dir)
        assert paths, f"{finder.__name__} found nothing"
        for p in paths:
            rel = art.rel_posix(p, shot_dir)
            assert not rel.startswith(".."), rel
            assert art.safe_resolve_under(shot_dir, rel) is not None, rel
            url = art.file_url_for_path(30201, p, shot_dir)
            assert url.startswith("/shot-file/30201/")
            assert "v=" in url


def test_junction_plot_discovery(tmp_path: Path) -> None:
    if os.name != "nt":
        pytest.skip("junction test is Windows-specific")
    import subprocess

    shot_dir = tmp_path / "30201"
    real = shot_dir / "02_measured_data" / "05_plots"
    real.mkdir(parents=True)
    (real / "01_plasma_ip.png").write_bytes(_PNG)
    legacy = shot_dir / "experimental_data"
    r = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(legacy), str(shot_dir / "02_measured_data")],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f"mklink failed: {r.stderr}")
    # Discovery via real path
    paths = art.measured_plot_paths(shot_dir)
    assert paths
    rel = art.rel_posix(paths[0], shot_dir)
    assert art.safe_resolve_under(shot_dir, rel) is not None
    # Discovery when only legacy junction listing would work after wiping numbered leaf name
    # (still present — ensure junction folder itself is listable)
    via_legacy = art._list_images_flat(legacy / "05_plots", exts={".png"})
    assert via_legacy
    rel2 = art.rel_posix(via_legacy[0], shot_dir)
    assert art.safe_resolve_under(shot_dir, rel2) is not None


def test_file_url_and_fingerprint(tmp_path: Path) -> None:
    shot_dir = tmp_path / "30201"
    _fixture_shot(shot_dir)
    assert "download=1" in art.file_url(30201, "manifest.json", download=True)
    fp1 = art.results_fingerprint(shot_dir)
    fp2 = art.results_fingerprint(shot_dir)
    assert fp1 == fp2
    assert "30201" in fp1


def test_run_manager_start_mocked(tmp_path: Path) -> None:
    mgr = RunManager(log_maxlen=50)
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    fake_proc.pid = 12345
    fake_proc.stdout = iter(["[OK] hello\n", "[OK] done\n"])
    fake_proc.wait.return_value = 0

    with patch("mast_freegsnke_ui.run_manager.subprocess.Popen", return_value=fake_proc) as popen:
        mgr.start(30201, config=tmp_path / "configs" / "default.json", cwd=tmp_path)
        assert popen.called
        cmd = popen.call_args[0][0]
        assert "run" in cmd
        assert "30201" in cmd

    import time

    for _ in range(50):
        snap = mgr.snapshot()
        if snap.get("returncode") == 0 or any("hello" in ln for ln in (snap.get("log_lines") or [])):
            break
        time.sleep(0.05)
    snap = mgr.snapshot()
    assert snap["shot"] == 30201
    assert any("hello" in ln for ln in snap["log_lines"]) or snap["returncode"] == 0


def test_fill_all_tabs_have_distinct_content(tmp_path: Path) -> None:
    pytest.importorskip("dash")
    pytest.importorskip("dash_bootstrap_components")
    from mast_freegsnke_ui import panels

    shot_dir = tmp_path / "30201"
    _fixture_shot(shot_dir)
    bodies = {}
    for tid, _label in panels.TAB_DEFS:
        body = panels.fill_one_tab(tid, 30201, shot_dir)
        assert body is not None
        bodies[tid] = str(body)
    # Level-2 / EFIT / GIFs galleries must mention their image filenames
    assert "01_plasma_ip.png" in bodies["level2"]
    assert "ip.csv" in bodies["level2"]
    assert "l2-family" in bodies["level2"] or "l2-detail" in bodies["level2"]
    assert "Plasma" in bodies["level2"]
    assert "lcfs_compare.png" in bodies["efit"]
    assert "inverse_equilibria.gif" in bodies["gifs"]
    assert "fl_01" in bodies["residuals"]
    assert "voltage_map" in bodies["auth"] or "sha256" in bodies["auth"]
    assert "manifest.json" in bodies["files"] or "SUMMARY" in bodies["files"]
    # Overview uses click-to-expand subsections
    assert "Key performance" in bodies["overview"] or "accordion" in bodies["overview"].lower()


def test_level2_helpers_and_cache_status(tmp_path: Path) -> None:
    from mast_freegsnke_ui import level2 as l2

    shot_dir = tmp_path / "30201"
    _fixture_shot(shot_dir)
    assert l2.measured_root(shot_dir) is not None
    cat = l2.load_measured_catalog(shot_dir)
    assert cat and cat.get("shot") == 30201
    grouped = l2.measured_plots_grouped(shot_dir)
    assert grouped.get("plasma")
    csvs = l2.measured_csv_inventory(shot_dir)
    assert any(i["name"] == "ip.csv" for i in csvs)
    preview = l2.csv_preview_rows(shot_dir / "02_measured_data" / "01_plasma" / "ip.csv")
    assert preview and "ip" in preview[0]

    cache = tmp_path / "data_cache" / "shot_30201"
    (cache / "pf_active.zarr").mkdir(parents=True)
    (cache / "pf_active.zarr" / "zarr.json").write_text("{}", encoding="utf-8")
    (cache / "magnetics.zarr").mkdir(parents=True)
    (cache / "magnetics.zarr" / "zarr.json").write_text("{}", encoding="utf-8")
    st = l2.shot_cache_status(
        tmp_path / "data_cache",
        30201,
        required=["pf_active", "magnetics", "wall"],
    )
    assert st["partial"] is True
    assert st["ready"] is False
    assert "wall" in st["missing_required"]
    (cache / "wall.zarr").mkdir(parents=True)
    (cache / "wall.zarr" / "zarr.json").write_text("{}", encoding="utf-8")
    st2 = l2.shot_cache_status(
        tmp_path / "data_cache",
        30201,
        required=["pf_active", "magnetics", "wall"],
    )
    assert st2["ready"] is True


def test_check_groups_respecting_cache_skips_s3(tmp_path: Path) -> None:
    from mast_freegsnke.availability import GroupAvailability
    from mast_freegsnke.download import check_groups_respecting_cache

    shot_cache = tmp_path / "shot_42"
    (shot_cache / "pf_active.zarr").mkdir(parents=True)
    (shot_cache / "pf_active.zarr" / "zarr.json").write_text("{}", encoding="utf-8")

    called: list[str] = []

    def discover(shot: int, group: str) -> str:
        called.append(group)
        return f"s3://bucket/{group}/shot_{shot}.zarr"

    # Monkeypatch check_groups used inside respecting_cache via discover callback path:
    # only missing groups should hit discover through check_groups — stub via wrapping.
    from mast_freegsnke import download as dl_mod

    def fake_check_groups(*, shot, groups, discover):
        out = {}
        for g in groups:
            discover(shot, g)
            out[g] = GroupAvailability(group=g, exists=True, s3_path=f"s3://x/{g}", error=None)
        return out

    with patch.object(dl_mod, "check_groups", side_effect=fake_check_groups):
        avail = check_groups_respecting_cache(
            shot=42,
            groups=["pf_active", "magnetics"],
            discover=discover,
            shot_cache=shot_cache,
            allow_cache_reuse=True,
        )
    assert avail["pf_active"].exists
    assert str(avail["pf_active"].s3_path).startswith("local-cache:")
    assert called == ["magnetics"]  # only missing group probed


def test_create_app_serves_plots_and_tabs(tmp_path: Path) -> None:
    pytest.importorskip("dash")
    pytest.importorskip("dash_bootstrap_components")
    from mast_freegsnke_ui.app import create_app, _library_fingerprint
    from mast_freegsnke_ui import panels

    runs = tmp_path / "SHOT"
    _fixture_shot(runs / "30201")
    cache = tmp_path / "data_cache" / "shot_30201"
    (cache / "pf_active.zarr").mkdir(parents=True)
    (cache / "pf_active.zarr" / "zarr.json").write_text("{}", encoding="utf-8")
    cfg = tmp_path / "configs"
    cfg.mkdir()
    (cfg / "default.json").write_text(
        json.dumps({"cache_dir": str(tmp_path / "data_cache")}),
        encoding="utf-8",
    )
    # Must stay O(shots) — never grow by mutating the iterated shot list.
    fp = _library_fingerprint(runs, cache_dir=tmp_path / "data_cache")
    assert fp
    app = create_app(
        repo_root=tmp_path,
        runs_dir=runs,
        config_path=cfg / "default.json",
        run_manager=RunManager(),
    )
    assert app.title == "Fair-MAST → FreeGSNKE"
    assert app.layout is not None
    rules = {str(r) for r in app.server.url_map.iter_rules()}
    assert any("/shot-file/" in r for r in rules)
    assert any("/shot-zip/" in r for r in rules)

    client = app.server.test_client()
    r = client.get("/shot-file/30201/manifest.json")
    assert r.status_code == 200
    r2 = client.get("/shot-file/30201/../manifest.json")
    assert r2.status_code == 404
    r3 = client.get("/shot-zip/30201")
    assert r3.status_code == 200
    assert r3.mimetype == "application/zip"

    # Every discovered plot must be HTTP-reachable
    shot_dir = runs / "30201"
    for p in (
        art.measured_plot_paths(shot_dir)
        + art.residual_plot_paths(shot_dir)
        + art.efit_plot_paths(shot_dir)
        + art.gif_paths(shot_dir)
    ):
        url = art.file_url_for_path(30201, p, shot_dir)
        resp = client.get(url)
        assert resp.status_code == 200, url

    # Callback wiring: results tabs + body outputs exist
    outs = []
    for key, cb in app.callback_map.items():
        outs.extend(str(key).split("...") if isinstance(key, str) else [str(key)])
    joined = " ".join(outs) + " ".join(app.callback_map.keys())
    assert "tab-body" in joined
    assert "results-tabs" in joined

    assert art.list_shot_dirs(runs) == [30201]
    # Panel builder sanity for each tab id used by the app
    for tid, _ in panels.TAB_DEFS:
        assert panels.fill_one_tab(tid, 30201, shot_dir) is not None
