"""Declared time-dependent FreeGSNKE profile trajectory authority (ADR-004 Phase 1).

Knots carry ConstrainPaxisIp knobs (paxis, fvac, alpha_m, alpha_n). Values must come from
a cited fit (efit_profile_fit) or an explicit table — never invented mid-run.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and (x == x)


def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


FIT_MODES = frozenset({"archive_profiles", "scalar_bridge", "auto"})
INTERP_ORDERS = frozenset({"linear", "nearest"})


@dataclass(frozen=True)
class ProfileKnot:
    t_s: float
    paxis_Pa: float
    fvac: float
    alpha_m: float
    alpha_n: float
    residual: Optional[Dict[str, float]] = None

    def validate(self) -> None:
        _require(_is_number(self.t_s), "knot.t_s must be a number")
        _require(_is_number(self.paxis_Pa) and float(self.paxis_Pa) > 0.0, "knot.paxis_Pa must be > 0")
        _require(_is_number(self.fvac) and 0.0 <= float(self.fvac) <= 1.0, "knot.fvac must be in [0,1]")
        _require(_is_number(self.alpha_m) and float(self.alpha_m) > 0.0, "knot.alpha_m must be > 0")
        _require(_is_number(self.alpha_n) and float(self.alpha_n) > 0.0, "knot.alpha_n must be > 0")

    def to_json_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "t_s": float(self.t_s),
            "paxis_Pa": float(self.paxis_Pa),
            "fvac": float(self.fvac),
            "alpha_m": float(self.alpha_m),
            "alpha_n": float(self.alpha_n),
        }
        if self.residual is not None:
            d["residual"] = {str(k): float(v) for k, v in self.residual.items()}
        return d


@dataclass(frozen=True)
class ProfileTrajectoryPolicy:
    """Config-side policy for building / requiring a trajectory (not the knots themselves)."""

    authority_name: str = "profile_trajectory"
    authority_version: str = "1.0.0"
    enabled: bool = True
    require: bool = False
    source: str = "fairmast_level2_equilibrium"
    equilibrium_group: str = "equilibrium"
    basis_type: str = "ConstrainPaxisIp"
    fit_mode: str = "auto"
    knot_policy: str = "linspace_window_inclusive"
    n_knots: int = 11
    interpolation: str = "linear"
    wmhd_var: str = "wmhd"
    pprime_vars: Tuple[str, ...] = ("pprime", "p_prime", "p'")
    ffprime_vars: Tuple[str, ...] = ("ffprime", "ff_prime", "ff'")
    psi_n_vars: Tuple[str, ...] = ("psi_n", "psin", "normalized_poloidal_flux")
    scalar_bridge_formula: str = "paxis(t)=paxis_ref*wmhd(t)/wmhd_ref"
    notes: str = ""

    def validate(self) -> None:
        _require(isinstance(self.authority_name, str) and self.authority_name.strip(), "authority_name required")
        _require(isinstance(self.authority_version, str) and self.authority_version.strip(), "authority_version required")
        _require(isinstance(self.enabled, bool), "enabled must be bool")
        _require(isinstance(self.require, bool), "require must be bool")
        _require(self.source == "fairmast_level2_equilibrium", "source must be fairmast_level2_equilibrium")
        _require(self.equilibrium_group == "equilibrium", "equilibrium_group must be 'equilibrium'")
        _require(self.basis_type == "ConstrainPaxisIp", "basis_type must be ConstrainPaxisIp (v1)")
        _require(self.fit_mode in FIT_MODES, f"fit_mode must be one of {sorted(FIT_MODES)}")
        _require(
            self.knot_policy == "linspace_window_inclusive",
            "knot_policy must be linspace_window_inclusive (v1)",
        )
        _require(isinstance(self.n_knots, int) and 2 <= self.n_knots <= 500, "n_knots must be int in [2, 500]")
        _require(self.interpolation in INTERP_ORDERS, f"interpolation must be one of {sorted(INTERP_ORDERS)}")
        _require(isinstance(self.wmhd_var, str) and self.wmhd_var.strip(), "wmhd_var required")
        _require(isinstance(self.notes, str), "notes must be str")

    def to_json_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["pprime_vars"] = list(self.pprime_vars)
        d["ffprime_vars"] = list(self.ffprime_vars)
        d["psi_n_vars"] = list(self.psi_n_vars)
        return d


@dataclass
class ProfileTrajectory:
    """Built / declared trajectory snapshotted under inputs/profile_trajectory_authority/."""

    authority_name: str
    authority_version: str
    basis_type: str
    fit_mode_used: str
    interpolation: str
    status: str  # ok | skipped_insufficient_archive | awaiting_authority
    knots: List[ProfileKnot] = field(default_factory=list)
    provenance: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def validate(self) -> None:
        _require(isinstance(self.authority_name, str) and self.authority_name.strip(), "authority_name required")
        _require(isinstance(self.authority_version, str) and self.authority_version.strip(), "authority_version required")
        _require(self.basis_type == "ConstrainPaxisIp", "basis_type must be ConstrainPaxisIp")
        _require(
            self.fit_mode_used in FIT_MODES or self.fit_mode_used in ("none", "held_ic"),
            f"fit_mode_used invalid: {self.fit_mode_used!r}",
        )
        _require(self.interpolation in INTERP_ORDERS, f"interpolation must be one of {sorted(INTERP_ORDERS)}")
        _require(
            self.status in ("ok", "skipped_insufficient_archive", "awaiting_authority"),
            f"status invalid: {self.status!r}",
        )
        if self.status == "ok":
            _require(len(self.knots) >= 2, "ok trajectory requires >= 2 knots")
            for k in self.knots:
                k.validate()
            times = [float(k.t_s) for k in self.knots]
            _require(times == sorted(times), "knots must be sorted by t_s ascending")
            _require(len(set(times)) == len(times), "knot times must be unique")

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "authority_name": self.authority_name,
            "authority_version": self.authority_version,
            "basis_type": self.basis_type,
            "fit_mode_used": self.fit_mode_used,
            "interpolation": self.interpolation,
            "status": self.status,
            "knots": [k.to_json_dict() for k in self.knots],
            "provenance": dict(self.provenance),
            "notes": self.notes,
        }

    def content_sha256(self) -> str:
        payload = json.dumps(self.to_json_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_profile_trajectory_policy(path: Path) -> ProfileTrajectoryPolicy:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"profile_trajectory_authority not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("profile_trajectory_authority must be a JSON object")
    pol = ProfileTrajectoryPolicy(
        authority_name=str(obj.get("authority_name", "profile_trajectory")),
        authority_version=str(obj.get("authority_version", "1.0.0")),
        enabled=bool(obj.get("enabled", True)),
        require=bool(obj.get("require", False)),
        source=str(obj.get("source", "fairmast_level2_equilibrium")),
        equilibrium_group=str(obj.get("equilibrium_group", "equilibrium")),
        basis_type=str(obj.get("basis_type", "ConstrainPaxisIp")),
        fit_mode=str(obj.get("fit_mode", "auto")),
        knot_policy=str(obj.get("knot_policy", "linspace_window_inclusive")),
        n_knots=int(obj.get("n_knots", 11)),
        interpolation=str(obj.get("interpolation", "linear")),
        wmhd_var=str(obj.get("wmhd_var", "wmhd")),
        pprime_vars=tuple(obj.get("pprime_vars") or ("pprime", "p_prime", "p'")),
        ffprime_vars=tuple(obj.get("ffprime_vars") or ("ffprime", "ff_prime", "ff'")),
        psi_n_vars=tuple(obj.get("psi_n_vars") or ("psi_n", "psin", "normalized_poloidal_flux")),
        scalar_bridge_formula=str(
            obj.get("scalar_bridge_formula", "paxis(t)=paxis_ref*wmhd(t)/wmhd_ref")
        ),
        notes=str(obj.get("notes", "")),
    )
    pol.validate()
    return pol


def write_profile_trajectory_policy(inputs_dir: Path, policy: ProfileTrajectoryPolicy) -> Path:
    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "profile_trajectory_authority"
    root.mkdir(parents=True, exist_ok=True)
    policy.validate()
    path = root / "profile_trajectory_authority.json"
    path.write_text(json.dumps(policy.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_profile_trajectory(path: Path) -> ProfileTrajectory:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"profile_trajectory not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("profile_trajectory must be a JSON object")
    knots_raw = obj.get("knots") or []
    knots: List[ProfileKnot] = []
    for row in knots_raw:
        if not isinstance(row, Mapping):
            raise ValueError("each knot must be an object")
        res = row.get("residual")
        knots.append(
            ProfileKnot(
                t_s=float(row["t_s"]),
                paxis_Pa=float(row["paxis_Pa"]),
                fvac=float(row["fvac"]),
                alpha_m=float(row["alpha_m"]),
                alpha_n=float(row["alpha_n"]),
                residual=({str(k): float(v) for k, v in res.items()} if isinstance(res, Mapping) else None),
            )
        )
    traj = ProfileTrajectory(
        authority_name=str(obj.get("authority_name", "profile_trajectory")),
        authority_version=str(obj.get("authority_version", "1.0.0")),
        basis_type=str(obj.get("basis_type", "ConstrainPaxisIp")),
        fit_mode_used=str(obj.get("fit_mode_used", "none")),
        interpolation=str(obj.get("interpolation", "linear")),
        status=str(obj.get("status", "awaiting_authority")),
        knots=knots,
        provenance=dict(obj.get("provenance") or {}),
        notes=str(obj.get("notes", "")),
    )
    traj.validate()
    return traj


def write_profile_trajectory(inputs_dir: Path, traj: ProfileTrajectory) -> Path:
    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "profile_trajectory_authority"
    root.mkdir(parents=True, exist_ok=True)
    traj.validate()
    path = root / "profile_trajectory.json"
    payload = traj.to_json_dict()
    payload["content_sha256"] = traj.content_sha256()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def try_load_built_trajectory(inputs_dir: Path) -> Optional[ProfileTrajectory]:
    """Load snapshotted trajectory if present and status==ok; else None."""
    path = Path(inputs_dir) / "profile_trajectory_authority" / "profile_trajectory.json"
    if not path.exists():
        return None
    traj = load_profile_trajectory(path)
    if traj.status != "ok":
        return None
    return traj


def knot_times_linspace(t_start: float, t_end: float, n_knots: int) -> np.ndarray:
    _require(_is_number(t_start) and _is_number(t_end), "t_start/t_end must be numbers")
    _require(float(t_end) > float(t_start), "require t_end > t_start for knots")
    _require(isinstance(n_knots, int) and n_knots >= 2, "n_knots must be >= 2")
    return np.linspace(float(t_start), float(t_end), int(n_knots))


def interpolate_profile_at(
    traj: ProfileTrajectory,
    t_s: float,
) -> Dict[str, float]:
    """Interpolate ConstrainPaxisIp knobs at absolute time t_s."""
    traj.validate()
    _require(traj.status == "ok", "cannot interpolate non-ok trajectory")
    times = np.asarray([k.t_s for k in traj.knots], dtype=float)
    paxis = np.asarray([k.paxis_Pa for k in traj.knots], dtype=float)
    fvac = np.asarray([k.fvac for k in traj.knots], dtype=float)
    am = np.asarray([k.alpha_m for k in traj.knots], dtype=float)
    an = np.asarray([k.alpha_n for k in traj.knots], dtype=float)
    t = float(t_s)

    def _one(y: np.ndarray) -> float:
        if traj.interpolation == "nearest":
            i = int(np.argmin(np.abs(times - t)))
            return float(y[i])
        return float(np.interp(t, times, y))

    out = {
        "paxis": _one(paxis),
        "fvac": _one(fvac),
        "alpha_m": _one(am),
        "alpha_n": _one(an),
    }
    _require(out["paxis"] > 0.0, "interpolated paxis must be > 0")
    _require(0.0 <= out["fvac"] <= 1.0, "interpolated fvac must be in [0,1]")
    _require(out["alpha_m"] > 0.0 and out["alpha_n"] > 0.0, "interpolated alphas must be > 0")
    return out


def profiles_parameters_dict(knobs: Mapping[str, float]) -> Dict[str, float]:
    """FreeGSNKE nlstepper profiles_parameters keys (paxis, alpha_m, alpha_n)."""
    return {
        "paxis": float(knobs["paxis"]),
        "alpha_m": float(knobs["alpha_m"]),
        "alpha_n": float(knobs["alpha_n"]),
    }
