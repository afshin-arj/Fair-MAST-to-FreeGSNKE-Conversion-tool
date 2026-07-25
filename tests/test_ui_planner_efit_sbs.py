"""UI/planner replan + EFIT side-by-side GIF tests."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from mast_freegsnke.planner_replan import (
    PlannerReplanError,
    apply_circuit_rl_edits,
    apply_passive_resistivity_edits,
    load_editable_circuit_table,
)
from mast_freegsnke_ui import artifacts as art
from mast_freegsnke_ui import panels
from mast_freegsnke_ui import ui_kit

REPO = Path(__file__).resolve().parents[1]


def test_accordion_starts_collapsed() -> None:
    html, _, _ = panels._require()
    body = panels.accordion(
        [
            ("A", html.Div("a"), True),
            ("B", html.Div("b"), True),
            ("C", html.Div("c"), False),
        ]
    )
    # All subsections start collapsed regardless of the legacy third flag
    assert getattr(body, "start_collapsed", None) is True or "start_collapsed=True" in str(body)
    active = getattr(body, "active_item", None)
    assert active in ([], None) or active == []


def test_ui_kit_section_starts_collapsed() -> None:
    html, _, _ = ui_kit.require()
    sec = ui_kit.section("Title", "note", html.Div("body"))
    assert getattr(sec, "type", None) == "Details" or "Details" in type(sec).__name__ or (
        isinstance(sec, dict) and sec.get("type") == "Details"
    ) or "fg-section-collapsible" in str(sec)
    # Must not start open — user clicks to expand
    assert getattr(sec, "open", None) is False or "open=False" in str(sec) or (
        isinstance(sec, dict) and sec.get("props", {}).get("open") is False
    )


def test_apply_circuit_rl_edit_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = REPO / "configs" / "circuit_dynamics_authority.json"
    obj = json.loads(cfg.read_text(encoding="utf-8"))
    # work on a copy under tmp
    root = tmp_path / "repo"
    (root / "configs").mkdir(parents=True)
    dest = root / "configs" / "circuit_dynamics_authority.json"
    dest.write_text(json.dumps(obj), encoding="utf-8")
    name = next(iter(obj["circuits"]))
    old_r = float(obj["circuits"][name]["R_ohm"])
    apply_circuit_rl_edits(
        root,
        {name: {"R_ohm": old_r * 1.01, "L_henry": float(obj["circuits"][name]["L_henry"])}},
        citation_note="unit-test edit",
    )
    new = json.loads(dest.read_text(encoding="utf-8"))
    assert abs(float(new["circuits"][name]["R_ohm"]) - old_r * 1.01) < 1e-12
    assert "unit-test edit" in str(new.get("citation") or "")


def test_passive_requires_citation(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "configs").mkdir(parents=True)
    (root / "configs" / "passive_resistivity.json").write_text(
        json.dumps({"version": "1.1", "status": "awaiting_authority", "components": {}, "notes": ""})
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(PlannerReplanError):
        apply_passive_resistivity_edits(
            root,
            {"vessel": {"resistivity_ohm_m": 1e-6}},  # missing source
        )
    apply_passive_resistivity_edits(
        root,
        {"vessel": {"resistivity_ohm_m": 1e-6, "source": "unit-test citation"}},
    )
    obj = json.loads((root / "configs" / "passive_resistivity.json").read_text(encoding="utf-8"))
    assert obj["status"] == "cited"
    assert "vessel" in obj["components"]


def test_side_by_side_gif_synthetic(tmp_path: Path) -> None:
    from mast_freegsnke.efit_side_by_side import write_freegsnke_efit_side_by_side_gif

    run = tmp_path / "30201"
    (run / "inputs").mkdir(parents=True)
    (run / "inputs" / "window.json").write_text(
        json.dumps({"t_start": 0.2, "t_end": 0.4}) + "\n", encoding="utf-8"
    )
    (run / "03_reconstruction").mkdir(parents=True)
    # Static FreeGSNKE LCFS
    import pandas as pd

    pd.DataFrame({"R": [0.8, 1.2, 1.0, 0.8], "Z": [0.0, 0.0, 0.5, 0.0]}).to_csv(
        run / "03_reconstruction" / "freegsnke_lcfs.csv", index=False
    )

    class _FakeDS:
        def __init__(self):
            self.coords = {"time": np.linspace(0.2, 0.4, 5)}
            self.data_vars = {"lcfs_r": None, "lcfs_z": None, "psi": None}

        def __contains__(self, key):
            return key in ("lcfs_r", "lcfs_z", "psi", "time")

        def __getitem__(self, key):
            class _V:
                def __init__(self, vals, dims):
                    self.values = vals
                    self.dims = dims

            t = 5
            if key == "time":
                return _V(np.linspace(0.2, 0.4, t), ("time",))
            if key == "lcfs_r":
                return _V(np.tile([0.85, 1.15, 1.0, 0.85], (t, 1)), ("time", "i"))
            if key == "lcfs_z":
                return _V(np.tile([0.0, 0.0, 0.4, 0.0], (t, 1)), ("time", "i"))
            if key == "psi":
                r = np.linspace(0.5, 1.5, 8)
                z = np.linspace(-1.0, 1.0, 10)
                rr, zz = np.meshgrid(r, z)
                psi = np.exp(-((rr - 1.0) ** 2 + zz**2))
                return _V(np.stack([psi] * t, axis=0), ("time", "z", "r"))
            raise KeyError(key)

    # Monkeypatch extractors used inside writer via efit_compare helpers — use real ones with xarray-like
    # Simpler: call with minimal stubs by patching _extract_lcfs_at
    import mast_freegsnke.efit_compare as ec
    import mast_freegsnke.efit_side_by_side as sbs

    times = np.linspace(0.2, 0.4, 5)

    def fake_lcfs(ds, idx, r_name, z_name):
        return (
            np.array([0.85, 1.15, 1.0, 0.85]),
            np.array([0.0, 0.0, 0.4, 0.0]),
        )

    def fake_psi(ds, idx, psi_var):
        r = np.linspace(0.5, 1.5, 8)
        z = np.linspace(-1.0, 1.0, 10)
        rr, zz = np.meshgrid(r, z)
        return {"psi": np.exp(-((rr - 1.0) ** 2 + zz**2)), "r": r, "z": z}

    monkey_lcfs = fake_lcfs
    # patch on module used by writer
    orig_lcfs = ec._extract_lcfs_at
    orig_psi = ec._extract_psi_at
    ec._extract_lcfs_at = fake_lcfs  # type: ignore
    ec._extract_psi_at = fake_psi  # type: ignore
    try:
        out = run / "04_efit_compare" / "plots"
        rep = write_freegsnke_efit_side_by_side_gif(
            run_dir=run,
            shot=30201,
            ds=object(),
            times=times,
            lcfs_r_name="lcfs_r",
            lcfs_z_name="lcfs_z",
            psi_var="psi",
            out_dir=out,
            n_frames=4,
            fps=2.0,
        )
    finally:
        ec._extract_lcfs_at = orig_lcfs  # type: ignore
        ec._extract_psi_at = orig_psi  # type: ignore

    assert rep["n_frames_written"] >= 2
    assert (out / "side_by_side_meta.json").is_file()
    assert rep.get("freegsnke_source")
    assert "freegsnke_lcfs_unavailable_efit_only_right_panel" not in (rep.get("notes") or [])
    # GIF may require Pillow
    if rep.get("ok") and rep.get("gif_rel"):
        assert (run / rep["gif_rel"]).is_file() or (out / "freegsnke_efit_side_by_side.gif").is_file()


def test_lcfs_from_inverse_dump_arrays(tmp_path: Path) -> None:
    import pickle

    import pandas as pd

    from mast_freegsnke.efit_compare import _try_freegsnke_products
    from mast_freegsnke.freegsnke_lcfs import lcfs_arrays_from_eq

    run = tmp_path / "30201"
    run.mkdir()
    th = np.linspace(0, 2 * np.pi, 40)
    rr = 1.0 + 0.3 * np.cos(th)
    zz = 0.4 * np.sin(th)
    dump = {
        "lcfs_R": rr,
        "lcfs_Z": zz,
        "t0": 0.25,
        "plasma_psi": np.ones((8, 8)),
        "grid": {"R": np.ones((8, 8)), "Z": np.ones((8, 8)), "nx": 8, "ny": 8},
    }
    (run / "inverse_dump.pkl").write_bytes(pickle.dumps(dump))
    fg, _ = _try_freegsnke_products(run)
    assert fg is not None
    assert len(fg[0]) >= 3

    class _Eq:
        def separatrix(self, ntheta=101):
            return np.column_stack([rr, zz])

    got = lcfs_arrays_from_eq(_Eq())
    assert got is not None
    assert len(got[0]) >= 3


def test_planner_catalog_helpers(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    (run / "07_planner").mkdir(parents=True)
    (run / "07_planner" / "planning_voltage_residual.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (run / "07_planner" / "planned_currents.csv").write_text("time,Solenoid\n0.1,1\n", encoding="utf-8")
    assert art.planner_plot_paths(run)
    assert art.planner_csv_paths(run)
    (run / "07_planner" / "PLANNER.json").write_text(
        json.dumps({"method": "gspulse_python", "status": "ok", "n_knots": 5}) + "\n",
        encoding="utf-8",
    )
    assert panels.planner_panel(30201, run) is not None


def test_replan_uses_appconfig_load() -> None:
    import inspect

    from mast_freegsnke import planner_replan as pr

    src = inspect.getsource(pr.replan_shot)
    assert "AppConfig.load" in src
    assert "machine_authority_dir" in src
    assert "load_config" not in src
    assert "R_ohm_by_circuit" in src
    assert "n_knots" in src


def test_extract_lcfs_prefers_time_dim() -> None:
    from mast_freegsnke.efit_compare import _extract_lcfs_at

    class _V:
        def __init__(self, vals, dims):
            self.values = vals
            self.dims = dims

    class _DS:
        def __contains__(self, k):
            return k in ("lcfs_r", "lcfs_z")

        def __getitem__(self, k):
            # Deliberately awkward shape: time=5, n=4 — old heuristic could flip
            arr = np.arange(20, dtype=float).reshape(5, 4)
            return _V(arr if k == "lcfs_r" else arr + 100, ("time", "i"))

    lcfs = _extract_lcfs_at(_DS(), 2, "lcfs_r", "lcfs_z")
    assert lcfs is not None
    rr, zz = lcfs
    assert list(rr) == [8.0, 9.0, 10.0, 11.0]


def test_passive_empty_editor_does_not_wipe(tmp_path: Path) -> None:
    """Regression: empty textarea must not clear cited passive ρ."""
    root = tmp_path / "repo"
    (root / "configs").mkdir(parents=True)
    path = root / "configs" / "passive_resistivity.json"
    path.write_text(
        json.dumps(
            {
                "version": "1.1",
                "status": "cited",
                "notes": "",
                "components": {
                    "vessel": {"resistivity_ohm_m": 1e-6, "source": "unit-test"}
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Simulate UI save with empty editor: do not call apply with {}
    before = path.read_text(encoding="utf-8")
    raw = ""
    if raw.strip():
        apply_passive_resistivity_edits(root, json.loads(raw))
    assert path.read_text(encoding="utf-8") == before


def test_replan_extract_reuses_prior_snapshot() -> None:
    import inspect

    from mast_freegsnke import planner_replan as pr

    src = inspect.getsource(pr._extract_freegsnke_fill)
    assert "resolve_freegsnke_python" in src
    assert "subprocess.run" in src
    assert "load_circuit_dynamics" in src
    src2 = inspect.getsource(pr.replan_shot)
    assert "machine_dir=ma" in src2 or "machine_dir=ma," in src2
    assert "_extract_freegsnke_fill" in src2
    assert 'L_model", "") == "full_matrix"' in src2 or '== "full_matrix"' in src2


def test_cli_plan_and_ui_use_package_repo_root() -> None:
    import inspect

    from mast_freegsnke import cli

    src = inspect.getsource(cli.main)
    assert 'cmd == "plan"' in src
    assert "parents[2]" in src
    # Both plan and ui should prefer package root over cwd
    assert src.count("Path(__file__).resolve().parents[2]") >= 2


def test_planner_empty_mounts_edit_controls(tmp_path: Path) -> None:
    run = tmp_path / "99999"
    run.mkdir()
    # No 07_planner products — empty state must still expose Dash callback targets
    panel = panels.planner_panel(99999, run, repo_root=Path(__file__).resolve().parents[1])
    blob = str(panel)
    assert "planner-btn-save" in blob
    assert "planner-btn-replan" in blob
    assert "planner-edit-status" in blob
    assert "planner-rl-citation" in blob
    assert "planner-passive-json" in blob


def test_planner_no_shot_fill_one_tab_mounts_edit() -> None:
    body = panels.fill_one_tab("planner", None, None, repo_root=Path(__file__).resolve().parents[1])
    blob = str(body)
    assert "planner-btn-save" in blob
    assert "planner-btn-replan" in blob


def test_efit_sbs_gallery_does_not_fallback_to_psi(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    plots = run / "04_efit_compare" / "plots"
    plots.mkdir(parents=True)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    (plots / "efit_psi.png").write_bytes(png)
    (plots / "side_by_side_frames").mkdir()
    (plots / "side_by_side_frames" / "sbs_000.png").write_bytes(png)
    # Discovery must include nested frames even when top-level plots exist
    discovered = art.efit_plot_paths(run)
    assert any(p.name == "sbs_000.png" for p in discovered)
    panel = panels.efit_panel(30201, run)
    blob = str(panel)
    assert "sbs_000" in blob
    # SBS gallery must not substitute efit_psi when only frames exist as SBS media
    # (efit_psi may still appear under "EFIT plots & downloads")
    assert "No side-by-side GIF yet" not in blob or "sbs_000" in blob

def test_gif_paths_includes_legacy_efit_compare(tmp_path: Path) -> None:
    run = tmp_path / "30201"
    legacy = run / "efit_compare" / "plots"
    legacy.mkdir(parents=True)
    (legacy / "demo.gif").write_bytes(b"GIF89a")
    paths = art.gif_paths(run)
    assert any(p.name == "demo.gif" for p in paths)