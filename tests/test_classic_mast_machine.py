"""Classic MAST FreeGSNKE machine from FAIR-MAST Level-2 (v11.3.0)."""
from __future__ import annotations

import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mast_freegsnke.classic_mast_machine import (
    CLASSIC_CIRCUIT_ORDER,
    FREEGSNKE_DEFAULT_COPPER_RESISTIVITY,
    build_active_coils_from_pf_zarr,
    limiter_from_flux_loop_rz,
    limiter_from_wall_rz,
    write_classic_mast_machine,
)
from mast_freegsnke.coil_map import load_coil_map
from mast_freegsnke.voltage_map import (
    apply_voltage_map,
    load_voltage_map,
    validate_voltage_map,
    voltage_map_drive_summary,
)

REPO = Path(__file__).resolve().parents[1]
SHOT_CACHE = REPO / "data_cache" / "shot_30201"


@pytest.mark.skipif(
    not (SHOT_CACHE / "pf_active.zarr").exists(),
    reason="data_cache/shot_30201/pf_active.zarr not present",
)
def test_build_active_coils_classic_keys() -> None:
    active = build_active_coils_from_pf_zarr(SHOT_CACHE / "pf_active.zarr")
    assert list(active.keys()) == list(CLASSIC_CIRCUIT_ORDER)
    assert "R" in active["Solenoid"] and "Z" in active["Solenoid"]
    assert len(active["Solenoid"]["R"]) == 656
    assert active["Solenoid"]["resistivity"] == FREEGSNKE_DEFAULT_COPPER_RESISTIVITY
    assert set(active["P4"].keys()) == {"1", "2"}
    assert "R" in active["P4"]["1"]
    for bad in ("D1", "D2", "D3", "Dp", "D5", "D6", "D7", "PX"):
        assert bad not in active


def test_limiter_from_wall_preserves_order() -> None:
    r = [1.0, 1.5, 1.5, 1.0]
    z = [0.0, 0.0, 1.0, 1.0]
    pts, meta = limiter_from_wall_rz(r, z, comment="Data sourced from EFIT file")
    assert meta["source"] == "wall.zarr"
    assert meta["not_cad_vessel"] is True
    assert "EFIT" in meta["provenance"]
    assert "CAD" in meta["provenance"]
    # Closed: first point appended when open.
    assert pts[0] == pts[-1]
    assert [(p["R"], p["Z"]) for p in pts[:-1]] == list(zip(r, z))


def test_limiter_from_flux_loops_sorted_by_angle() -> None:
    # Square about origin — angle sort should visit in CCW order from -pi.
    r = [1.0, 0.0, -1.0, 0.0]
    z = [0.0, 1.0, 0.0, -1.0]
    pts, meta = limiter_from_flux_loop_rz(r, z)
    assert meta["n_points"] == 4
    assert meta.get("fallback") is True
    assert "flux-loop" in meta["provenance"].lower() or "FALLBACK" in meta["provenance"]
    angs = [float(np.arctan2(p["Z"] - meta["centroid_Z_m"], p["R"] - meta["centroid_R_m"])) for p in pts]
    assert angs == sorted(angs)


@pytest.mark.skipif(
    not (SHOT_CACHE / "pf_active.zarr").exists()
    or not (SHOT_CACHE / "wall.zarr").exists(),
    reason="data_cache/shot_30201 incomplete (need pf_active + wall)",
)
def test_write_classic_machine_and_optional_tokamak(tmp_path: Path) -> None:
    out = tmp_path / "machine"
    rep = write_classic_mast_machine(
        SHOT_CACHE,
        out,
        shot=30201,
        archive_mastu=False,
        validate_tokamak=False,
    )
    assert rep["ok"]
    assert rep["circuits"] == list(CLASSIC_CIRCUIT_ORDER)
    assert rep["limiter_meta"]["source"] == "wall.zarr"
    assert rep["n_limiter_points"] == 37  # FAIR-MAST wall already closed (37 pts)
    with open(out / "active_coils.pickle", "rb") as f:
        active = pickle.load(f)
    assert list(active.keys()) == list(CLASSIC_CIRCUIT_ORDER)
    with open(out / "passive_coils.pickle", "rb") as f:
        assert pickle.load(f) == []
    with open(out / "limiter.pickle", "rb") as f:
        lim = pickle.load(f)
    assert isinstance(lim, list) and len(lim) == 37
    prov = json.loads((out / "FREEGSNKE_MACHINE_PROVENANCE.json").read_text(encoding="utf-8"))
    assert prov["machine"] == "classic_MAST"
    assert prov["limiter"]["source"] == "wall.zarr"
    assert isinstance(prov["passives"], dict)
    assert prov["passives"]["passives_written"] == []
    assert "resistivity" in prov["passives"]["reason"].lower()
    assert FREEGSNKE_DEFAULT_COPPER_RESISTIVITY == prov["resistivity_ohm_m"]
    limits = " ".join(prov.get("honest_limits") or [])
    assert "CAD" in limits and "P3/P6" in limits and "1.55" in limits

    # Tokamak validation if FreeGSNKE is importable in this interpreter.
    try:
        from freegsnke.build_machine import tokamak  # noqa: F401

        from mast_freegsnke.classic_mast_machine import validate_classic_tokamak

        tv = validate_classic_tokamak(out)
        if not tv.get("skipped"):
            assert tv["ok"], tv
            assert tv["active_keys"] == list(CLASSIC_CIRCUIT_ORDER)
    except ImportError:
        pass


def test_shipped_voltage_map_classic_no_divertors() -> None:
    vmap = load_voltage_map(REPO / "configs" / "voltage_map.json")
    rep = validate_voltage_map(vmap)
    assert rep["ok"], rep["errors"]
    assert vmap.machine_active_circuit_order == list(CLASSIC_CIRCUIT_ORDER)
    for bad in ("D1", "D2", "D3", "Dp", "D5", "D6", "D7", "PX"):
        assert bad not in vmap.circuits
        assert bad not in vmap.machine_active_circuit_order
    assert vmap.circuits["Solenoid"]["voltage_channels"] == ["p1"]
    assert vmap.circuits["P2_inner"]["voltage_channels"] == ["p2"]
    assert vmap.circuits["P2_outer"]["voltage_channels"] == ["p2"]
    assert vmap.circuits["P3"]["combine"] == "from_current_ohmic"
    assert vmap.circuits["P6"]["combine"] == "from_current_ohmic"
    drive = voltage_map_drive_summary(vmap)
    assert drive["n_measured"] == 5  # Solenoid + P2_inner + P2_outer + P4 + P5
    assert drive["n_ohmic"] == 2
    assert drive["n_zero_drive"] == 0
    assert "MAST-U" not in drive["line"]


def test_coil_map_matches_classic_circuits() -> None:
    cm = load_coil_map(REPO / "configs" / "coil_map.json")
    assert set(cm.circuits.keys()) == set(CLASSIC_CIRCUIT_ORDER)


def test_apply_voltage_map_classic_columns(tmp_path: Path) -> None:
    raw = tmp_path / "pf_voltages_raw.csv"
    pd.DataFrame(
        {
            "time": [0.0, 0.1],
            "p1": [1.0, 2.0],
            "p2": [3.0, 4.0],
            "p4": [5.0, 6.0],
            "p5": [7.0, 8.0],
        }
    ).to_csv(raw, index=False)
    currents = tmp_path / "pf_currents.csv"
    pd.DataFrame(
        {
            "time": [0.0, 0.1],
            "P3": [10.0, 20.0],
            "P6": [100.0, 200.0],
        }
    ).to_csv(currents, index=False)
    vmap = load_voltage_map(REPO / "configs" / "voltage_map.json")
    out = tmp_path / "pf_voltages.csv"
    rep = apply_voltage_map(raw, out, vmap, pf_currents_csv=currents)
    assert rep["ok"], rep["errors"]
    df = pd.read_csv(out)
    assert list(df.columns) == ["time"] + list(CLASSIC_CIRCUIT_ORDER)
    assert list(df["Solenoid"]) == pytest.approx([1.0, 2.0])
    assert list(df["P2_inner"]) == pytest.approx([3.0, 4.0])
    assert list(df["P2_outer"]) == pytest.approx([3.0, 4.0])
    assert list(df["P4"]) == pytest.approx([5.0, 6.0])
    assert list(df["P5"]) == pytest.approx([7.0, 8.0])
    # ohmic deferred without R
    assert pd.isna(df["P3"]).all()
    assert pd.isna(df["P6"]).all()
