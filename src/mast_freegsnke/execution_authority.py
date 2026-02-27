"""Execution-state authority for FreeGSNKE runs.

This module makes the *entire* numerical execution state explicit and hash-lockable,
eliminating hidden defaults inside generated FreeGSNKE driver scripts.

Authority scope (v10.0.0):
  - Grid/resolution spec
  - Profile parameterization spec (ConstrainPaxisIp)
  - Boundary / inverse-constraint spec
  - Solver control spec (tolerances, iteration knobs, L2 regularization policy)
  - Passive structure placeholder (reserved for future wiring)

Design laws:
  - Deterministic, audit-ready JSONs
  - Fail-fast validation
  - Defaults preserve v8 behavior unless user edits the authority bundle

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and (x == x)  # NaN-safe


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


@dataclass(frozen=True)
class GridSpec:
    Rmin: float
    Rmax: float
    Zmin: float
    Zmax: float
    nx: int
    ny: int

    def validate(self) -> None:
        _require(_is_number(self.Rmin) and _is_number(self.Rmax), "GridSpec: Rmin/Rmax must be numbers")
        _require(_is_number(self.Zmin) and _is_number(self.Zmax), "GridSpec: Zmin/Zmax must be numbers")
        _require(float(self.Rmax) > float(self.Rmin), "GridSpec: require Rmax > Rmin")
        _require(float(self.Zmax) > float(self.Zmin), "GridSpec: require Zmax > Zmin")
        _require(isinstance(self.nx, int) and self.nx >= 8, "GridSpec: nx must be int >= 8")
        _require(isinstance(self.ny, int) and self.ny >= 8, "GridSpec: ny must be int >= 8")


@dataclass(frozen=True)
class ConstrainPaxisIpSpec:
    """Parameterization for freegsnke.jtor_update.ConstrainPaxisIp.

    Notes
    -----
    Ip is sourced dynamically at runtime from the chosen t0 (formed-plasma time)
    and passed into ConstrainPaxisIp; this spec governs only the *closure knobs*.
    """

    paxis_Pa: float
    fvac: float
    alpha_m: float
    alpha_n: float

    def validate(self) -> None:
        _require(_is_number(self.paxis_Pa) and float(self.paxis_Pa) > 0.0, "ProfileSpec: paxis_Pa must be > 0")
        _require(_is_number(self.fvac), "ProfileSpec: fvac must be a number")
        _require(0.0 <= float(self.fvac) <= 1.0, "ProfileSpec: fvac must be in [0,1]")
        _require(_is_number(self.alpha_m) and float(self.alpha_m) > 0.0, "ProfileSpec: alpha_m must be > 0")
        _require(_is_number(self.alpha_n) and float(self.alpha_n) > 0.0, "ProfileSpec: alpha_n must be > 0")


@dataclass(frozen=True)
class ProfileBasisSpec:
    """Govern the functional basis used for profile representation.

    FreeGSNKE's ConstrainPaxisIp parameterization has an *implicit* basis inside
    FreeGSNKE; this authority object exists to prevent silent changes in that
    implicit representation from going unnoticed.

    This is intentionally descriptive rather than prescriptive until additional
    basis options are wired.
    """

    basis_type: str = "ConstrainPaxisIp"
    knot_policy: str = "implicit"
    interpolation_order: int = 3
    regularization: str = "none"
    notes: str = ""

    def validate(self) -> None:
        _require(isinstance(self.basis_type, str) and self.basis_type.strip(), "ProfileBasisSpec: basis_type required")
        _require(isinstance(self.knot_policy, str) and self.knot_policy.strip(), "ProfileBasisSpec: knot_policy required")
        _require(isinstance(self.interpolation_order, int) and self.interpolation_order >= 1, "ProfileBasisSpec: interpolation_order must be int >= 1")
        _require(isinstance(self.regularization, str), "ProfileBasisSpec: regularization must be str")
        _require(isinstance(self.notes, str), "ProfileBasisSpec: notes must be str")


@dataclass(frozen=True)
class BoundarySpec:
    """Inverse-shape constraints for freegsnke.inverse.Inverse_optimizer."""

    # null_points are stored as [[Rx, Ro],[Zx, Zo]] (v8 template convention)
    null_points: List[List[float]]
    # isoflux_set stored as nested list shaped like freegsnke expects (see templates)
    isoflux_set: List[List[List[float]]]

    def validate(self) -> None:
        _require(isinstance(self.null_points, list) and len(self.null_points) == 2, "BoundarySpec: null_points must be 2x2 list")
        _require(all(isinstance(r, list) and len(r) == 2 for r in self.null_points), "BoundarySpec: null_points must be 2x2 list")
        for r in self.null_points:
            _require(all(_is_number(v) for v in r), "BoundarySpec: null_points values must be numbers")
        _require(isinstance(self.isoflux_set, list) and len(self.isoflux_set) >= 1, "BoundarySpec: isoflux_set must be non-empty list")
        # Light structural validation only (exact shape may vary)
        _require(isinstance(self.isoflux_set[0], list), "BoundarySpec: isoflux_set outer element must be list")


@dataclass(frozen=True)
class L2RegSpec:
    default: float = 1e-8
    per_coil_override: Dict[str, float] = field(default_factory=dict)

    def validate(self) -> None:
        _require(_is_number(self.default) and float(self.default) >= 0.0, "L2RegSpec: default must be >= 0")
        _require(isinstance(self.per_coil_override, dict), "L2RegSpec: per_coil_override must be dict")
        for k, v in self.per_coil_override.items():
            _require(isinstance(k, str) and k, "L2RegSpec: override keys must be non-empty strings")
            _require(_is_number(v) and float(v) >= 0.0, f"L2RegSpec: override {k} must be >= 0")


@dataclass(frozen=True)
class SolverSpec:
    inverse_target_relative_tolerance: float
    inverse_target_relative_psit_update: float
    forward_target_relative_tolerance: float
    l2_reg: L2RegSpec

    def validate(self) -> None:
        for name, val in [
            ("inverse_target_relative_tolerance", self.inverse_target_relative_tolerance),
            ("inverse_target_relative_psit_update", self.inverse_target_relative_psit_update),
            ("forward_target_relative_tolerance", self.forward_target_relative_tolerance),
        ]:
            _require(_is_number(val) and 0.0 < float(val) < 1.0, f"SolverSpec: {name} must be in (0,1)")
        self.l2_reg.validate()


@dataclass(frozen=True)
class PassiveStructureSpec:
    """Reserved scaffold for future FreeGSNKE passive structure governance."""

    enabled: bool = False
    model: str = "none"
    parameters: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        _require(isinstance(self.enabled, bool), "PassiveStructureSpec: enabled must be bool")
        _require(isinstance(self.model, str), "PassiveStructureSpec: model must be str")
        _require(isinstance(self.parameters, dict), "PassiveStructureSpec: parameters must be dict")


@dataclass(frozen=True)
class ExecutionAuthorityBundle:
    """Top-level bundle for execution-state authority."""

    authority_name: str
    authority_version: str
    grid: GridSpec
    profile: ConstrainPaxisIpSpec
    profile_basis: ProfileBasisSpec
    boundary: BoundarySpec
    solver: SolverSpec
    passive_structure: PassiveStructureSpec

    def validate(self) -> None:
        _require(isinstance(self.authority_name, str) and self.authority_name.strip(), "Bundle: authority_name required")
        _require(isinstance(self.authority_version, str) and self.authority_version.strip(), "Bundle: authority_version required")
        self.grid.validate()
        self.profile.validate()
        self.profile_basis.validate()
        self.boundary.validate()
        self.solver.validate()
        self.passive_structure.validate()

    def to_json_dict(self) -> Dict[str, Any]:
        # dataclasses.asdict is deterministic for insertion order in Python 3.7+.
        return asdict(self)


def default_execution_authority_bundle() -> ExecutionAuthorityBundle:
    """Defaults that reproduce v8.0.0 template behavior."""

    grid = GridSpec(Rmin=0.1, Rmax=2.0, Zmin=-2.2, Zmax=2.2, nx=65, ny=129)

    profile = ConstrainPaxisIpSpec(paxis_Pa=8e3, fvac=0.5, alpha_m=1.8, alpha_n=1.2)

    profile_basis = ProfileBasisSpec(
        basis_type="ConstrainPaxisIp",
        knot_policy="implicit",
        interpolation_order=3,
        regularization="none",
        notes="FreeGSNKE ConstrainPaxisIp basis is implicit; this authority prevents silent changes.",
    )

    boundary = BoundarySpec(
        null_points=[[1.45, 0.90], [-1.60, 0.00]],
        isoflux_set=[
            [
                [1.45, 0.60, 1.40, 1.25, 1.45, 1.65],
                [-1.60, 0.00, 0.00, -1.45, -1.62, -1.45],
            ]
        ],
    )

    solver = SolverSpec(
        inverse_target_relative_tolerance=1e-3,
        inverse_target_relative_psit_update=1e-3,
        forward_target_relative_tolerance=1e-6,
        l2_reg=L2RegSpec(default=1e-8, per_coil_override={"P6": 1e-5}),
    )

    return ExecutionAuthorityBundle(
        authority_name="freegsnke_execution_authority",
        authority_version="10.0.0",
        grid=grid,
        profile=profile,
        profile_basis=profile_basis,
        boundary=boundary,
        solver=solver,
        passive_structure=PassiveStructureSpec(),
    )


def write_execution_authority(inputs_dir: Path) -> Path:
    """Write the execution authority bundle under inputs/.

    Parameters
    ----------
    inputs_dir:
        The run inputs directory (run_dir/inputs).

    Returns
    -------
    root:
        Path to inputs/execution_authority directory.
    """

    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "execution_authority"
    root.mkdir(parents=True, exist_ok=True)

    bundle = default_execution_authority_bundle()
    bundle.validate()

    (root / "execution_authority_bundle.json").write_text(json.dumps(bundle.to_json_dict(), indent=2) + "\n")
    (root / "grid_spec.json").write_text(json.dumps(asdict(bundle.grid), indent=2) + "\n")
    (root / "profile_spec.json").write_text(json.dumps(asdict(bundle.profile), indent=2) + "\n")
    (root / "profile_basis_authority.json").write_text(json.dumps(asdict(bundle.profile_basis), indent=2) + "\n")
    (root / "boundary_spec.json").write_text(json.dumps(asdict(bundle.boundary), indent=2) + "\n")
    (root / "solver_spec.json").write_text(json.dumps(asdict(bundle.solver), indent=2) + "\n")
    (root / "passive_structure.json").write_text(json.dumps(asdict(bundle.passive_structure), indent=2) + "\n")

    return root


def load_execution_authority_bundle(bundle_path: Path) -> ExecutionAuthorityBundle:
    bundle_path = Path(bundle_path)
    obj = json.loads(bundle_path.read_text())
    _require(isinstance(obj, dict), "Execution authority bundle must be a JSON object")

    grid = GridSpec(**obj["grid"])
    profile = ConstrainPaxisIpSpec(**obj["profile"])
    profile_basis = ProfileBasisSpec(**obj.get("profile_basis", {}))
    boundary = BoundarySpec(**obj["boundary"])
    l2_reg = L2RegSpec(**obj["solver"]["l2_reg"])
    solver = SolverSpec(
        inverse_target_relative_tolerance=obj["solver"]["inverse_target_relative_tolerance"],
        inverse_target_relative_psit_update=obj["solver"]["inverse_target_relative_psit_update"],
        forward_target_relative_tolerance=obj["solver"]["forward_target_relative_tolerance"],
        l2_reg=l2_reg,
    )
    passive = PassiveStructureSpec(**obj.get("passive_structure", {}))

    bundle = ExecutionAuthorityBundle(
        authority_name=str(obj.get("authority_name", "")),
        authority_version=str(obj.get("authority_version", "")),
        grid=grid,
        profile=profile,
        profile_basis=profile_basis,
        boundary=boundary,
        solver=solver,
        passive_structure=passive,
    )
    bundle.validate()
    return bundle
