"""Archive X + LCFS → Inverse BoundarySpec remap (no invented metrology)."""

from __future__ import annotations

import json
from pathlib import Path

from mast_freegsnke.boundary_from_shape import (
    apply_shape_targets_to_execution_boundary,
    boundary_from_shape_knot,
    pick_shape_knot,
)
from mast_freegsnke.execution_authority import (
    BoundarySpec,
    default_execution_authority_bundle,
    write_execution_authority,
)


def test_boundary_from_shape_knot_prepends_archive_x() -> None:
    fallback = default_execution_authority_bundle().boundary
    knot = {
        "t_s": 0.25,
        "scalars": {
            "x_point_r": 1.10,
            "x_point_z": -1.25,
            "magnetic_axis_r": 0.95,
            "magnetic_axis_z": 0.02,
        },
        "control_points": {
                            "r_m": [0.7, 1.2, 1.4, 1.2, 0.7],
                            "z_m": [0.0, 0.8, 0.0, -0.8, 0.0],
                        },
    }
    spec, prov = boundary_from_shape_knot(knot, fallback=fallback)
    assert spec is not None
    assert prov["ok"] is True
    assert spec.null_points[0][0] == 1.10
    assert spec.null_points[1][0] == -1.25
    assert spec.null_points[0][1] == 0.95
    # Archive X is first isoflux point so ψ_bndry is forced through divertor null
    assert spec.isoflux_set[0][0][0] == 1.10
    assert spec.isoflux_set[0][1][0] == -1.25
    assert prov["isoflux_source"] == "lcfs_control_points_with_archive_x"


def test_boundary_from_shape_skips_missing_x() -> None:
    fallback = default_execution_authority_bundle().boundary
    knot = {"t_s": 0.1, "scalars": {"magnetic_axis_r": 0.9, "magnetic_axis_z": 0.0}}
    spec, prov = boundary_from_shape_knot(knot, fallback=fallback)
    assert spec is None
    assert prov["error"] == "missing_archive_x_point"


def test_apply_rewrites_execution_authority(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    write_execution_authority(inputs, metrics_n_times=5)
    st_dir = inputs / "shape_targets_authority"
    st_dir.mkdir(parents=True)
    (st_dir / "shape_targets.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "knots": [
                    {
                        "t_s": 0.2,
                        "scalars": {
                            "x_point_r": 1.20,
                            "x_point_z": -1.40,
                            "magnetic_axis_r": 0.92,
                            "magnetic_axis_z": 0.01,
                        },
                        "control_points": {
                            "r_m": [0.6, 1.0, 1.3, 1.0],
                            "z_m": [0.0, 0.7, 0.0, -0.7],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rep = apply_shape_targets_to_execution_boundary(inputs, t_s=0.2)
    assert rep["ok"] is True
    assert rep["status"] == "ok"
    bnd = json.loads(
        (inputs / "execution_authority" / "boundary_spec.json").read_text(encoding="utf-8")
    )
    assert bnd["null_points"][0][0] == 1.20
    assert bnd["null_points"][1][0] == -1.40
    prov = json.loads(
        (inputs / "execution_authority" / "boundary_from_shape_targets.json").read_text(
            encoding="utf-8"
        )
    )
    assert prov["ok"] is True


def test_pick_shape_knot_nearest_time() -> None:
    st = {
        "knots": [
            {"t_s": 0.10, "scalars": {}},
            {"t_s": 0.30, "scalars": {}},
            {"t_s": 0.50, "scalars": {}},
        ]
    }
    k = pick_shape_knot(st, t_s=0.28)
    assert k is not None
    assert k["t_s"] == 0.30


def test_boundary_spec_allows_more_than_two_nulls() -> None:
    # DN: X_lower, O, X_upper
    spec = BoundarySpec(
        null_points=[[1.1, 0.9, 1.1], [-1.3, 0.0, 1.3]],
        isoflux_set=[[[1.1, 0.7], [-1.3, 0.0]]],
    )
    spec.validate()
