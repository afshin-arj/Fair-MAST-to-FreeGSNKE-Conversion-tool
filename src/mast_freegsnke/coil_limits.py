"""Coil I/V limits authority — ADR-004 Phase 2 hard gate (never invent limits)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd


class CoilLimitsError(ValueError):
    pass


LIMIT_POLICIES = frozenset({"fixed", "measured_peak_margin"})


@dataclass(frozen=True)
class CircuitLimit:
    Imax_A: float
    Vmax_V: float
    Imin_A: Optional[float] = None
    Vmin_V: Optional[float] = None
    notes: str = ""

    def validate(self, name: str) -> None:
        if not isinstance(self.Imax_A, (int, float)) or float(self.Imax_A) <= 0:
            raise CoilLimitsError(f"{name}: Imax_A must be > 0 (got {self.Imax_A!r})")
        if not isinstance(self.Vmax_V, (int, float)) or float(self.Vmax_V) <= 0:
            raise CoilLimitsError(f"{name}: Vmax_V must be > 0 (got {self.Vmax_V!r})")
        imin = float(self.Imin_A) if self.Imin_A is not None else -float(self.Imax_A)
        vmin = float(self.Vmin_V) if self.Vmin_V is not None else -float(self.Vmax_V)
        if imin >= float(self.Imax_A):
            raise CoilLimitsError(f"{name}: Imin_A must be < Imax_A")
        if vmin >= float(self.Vmax_V):
            raise CoilLimitsError(f"{name}: Vmin_V must be < Vmax_V")

    def i_bounds(self) -> tuple[float, float]:
        lo = float(self.Imin_A) if self.Imin_A is not None else -float(self.Imax_A)
        return lo, float(self.Imax_A)

    def v_bounds(self) -> tuple[float, float]:
        lo = float(self.Vmin_V) if self.Vmin_V is not None else -float(self.Vmax_V)
        return lo, float(self.Vmax_V)

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "Imax_A": float(self.Imax_A),
            "Vmax_V": float(self.Vmax_V),
            "Imin_A": (float(self.Imin_A) if self.Imin_A is not None else None),
            "Vmin_V": (float(self.Vmin_V) if self.Vmin_V is not None else None),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CoilLimitsAuthority:
    authority_name: str
    authority_version: str
    status: str
    circuits: Dict[str, CircuitLimit]
    citation: Optional[str] = None
    notes: str = ""
    limit_policy: str = "fixed"
    margin_factor: Optional[float] = None
    resolution: Optional[Dict[str, Any]] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def awaiting(self) -> bool:
        st = self.status.strip().lower()
        if st in {"awaiting_authority", "awaiting", "empty", ""}:
            return True
        if self.limit_policy == "measured_peak_margin":
            return (
                self.margin_factor is None
                or float(self.margin_factor) <= 1.0
                or not (self.citation and str(self.citation).strip())
            )
        return not self.circuits

    def validate(self) -> None:
        if not self.authority_name.strip():
            raise CoilLimitsError("authority_name required")
        if not self.authority_version.strip():
            raise CoilLimitsError("authority_version required")
        if self.limit_policy not in LIMIT_POLICIES:
            raise CoilLimitsError(f"limit_policy must be one of {sorted(LIMIT_POLICIES)}")
        if self.awaiting:
            return
        if not self.citation or not str(self.citation).strip():
            raise CoilLimitsError(
                "coil_limits requires citation (plant doc / declared user policy) "
                "— never invent Imax/Vmax"
            )
        if self.limit_policy == "measured_peak_margin":
            if self.margin_factor is None or float(self.margin_factor) <= 1.0:
                raise CoilLimitsError("measured_peak_margin requires margin_factor > 1")
        else:
            if not self.circuits:
                raise CoilLimitsError("fixed limit_policy requires non-empty circuits")
            for name, lim in self.circuits.items():
                lim.validate(name)

    def require_ready(self, circuit_order: List[str]) -> None:
        """Fail-closed for planner solve (circuits must already be resolved numbers)."""
        self.validate()
        if self.awaiting:
            raise CoilLimitsError(
                "coil_limits_authority awaiting — cite fixed Imax/Vmax or "
                "measured_peak_margin policy before execute_planner "
                "(ADR-004 hard gate; never invent limits)"
            )
        if self.limit_policy == "measured_peak_margin" and not self.circuits:
            raise CoilLimitsError(
                "coil_limits measured_peak_margin not yet resolved to numeric circuits "
                "— call resolve_measured_peak_limits before planner"
            )
        missing = [c for c in circuit_order if c not in self.circuits]
        if missing:
            raise CoilLimitsError(
                f"coil_limits missing circuits required by voltage_map order: {missing}"
            )
        for name in circuit_order:
            self.circuits[name].validate(name)

    def to_json_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "authority_name": self.authority_name,
            "authority_version": self.authority_version,
            "status": self.status,
            "limit_policy": self.limit_policy,
            "citation": self.citation,
            "circuits": {k: v.to_json_dict() for k, v in self.circuits.items()},
            "notes": self.notes,
        }
        if self.margin_factor is not None:
            d["margin_factor"] = float(self.margin_factor)
        if self.resolution is not None:
            d["resolution"] = dict(self.resolution)
        return d


def load_coil_limits(path: Path) -> CoilLimitsAuthority:
    path = Path(path)
    if not path.exists():
        raise CoilLimitsError(f"coil_limits_authority not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise CoilLimitsError("coil_limits_authority must be a JSON object")
    raw_circuits = obj.get("circuits") or {}
    if not isinstance(raw_circuits, Mapping):
        raise CoilLimitsError("circuits must be an object")
    circuits: Dict[str, CircuitLimit] = {}
    for name, entry in raw_circuits.items():
        if not isinstance(entry, Mapping):
            raise CoilLimitsError(f"circuit {name!r} must be an object")
        circuits[str(name)] = CircuitLimit(
            Imax_A=float(entry["Imax_A"]),
            Vmax_V=float(entry["Vmax_V"]),
            Imin_A=(float(entry["Imin_A"]) if entry.get("Imin_A") is not None else None),
            Vmin_V=(float(entry["Vmin_V"]) if entry.get("Vmin_V") is not None else None),
            notes=str(entry.get("notes", "")),
        )
    policy = str(
        obj.get("limit_policy")
        or ("measured_peak_margin" if obj.get("margin_factor") else "fixed")
    )
    margin = obj.get("margin_factor")
    auth = CoilLimitsAuthority(
        authority_name=str(obj.get("authority_name", "coil_limits")),
        authority_version=str(obj.get("authority_version", "0.1.0")),
        status=str(obj.get("status", "awaiting_authority")),
        circuits=circuits,
        citation=(str(obj["citation"]) if obj.get("citation") else None),
        notes=str(obj.get("notes", "")),
        limit_policy=policy,
        margin_factor=(float(margin) if margin is not None else None),
        resolution=(dict(obj["resolution"]) if isinstance(obj.get("resolution"), dict) else None),
        raw=obj,
    )
    auth.validate()
    return auth


def write_coil_limits(inputs_dir: Path, auth: CoilLimitsAuthority) -> Path:
    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "coil_limits_authority"
    root.mkdir(parents=True, exist_ok=True)
    auth.validate()
    path = root / "coil_limits_authority.json"
    path.write_text(json.dumps(auth.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def _peak_abs_in_window(path: Path, circuit: str, t_start: float, t_end: float) -> float:
    if not path.exists():
        raise CoilLimitsError(f"missing measured file for limit resolution: {path}")
    df = pd.read_csv(path)
    if "time" not in df.columns or circuit not in df.columns:
        raise CoilLimitsError(f"{path.name} missing time or circuit column {circuit!r}")
    t = df["time"].to_numpy(dtype=float)
    y = df[circuit].to_numpy(dtype=float)
    mask = (t >= float(t_start) - 1e-12) & (t <= float(t_end) + 1e-12)
    if not np.any(mask):
        raise CoilLimitsError(
            f"{path.name}/{circuit}: no samples in planner window "
            f"[{t_start:.6g},{t_end:.6g}]"
        )
    vals = y[mask]
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        raise CoilLimitsError(
            f"{path.name}/{circuit}: no finite samples in planner window "
            f"[{t_start:.6g},{t_end:.6g}]"
        )
    peak = float(np.max(np.abs(vals)))
    if not np.isfinite(peak) or peak <= 0.0:
        raise CoilLimitsError(
            f"{path.name}/{circuit}: non-positive peak |signal|={peak} in window "
            "(cannot form margin limits)"
        )
    return peak


def _dynamics_v_peak_planner_consistent(
    i_path: Path,
    circuit_order: Sequence[str],
    *,
    t_start: float,
    t_end: float,
    n_knots: int,
    R_ohm: Sequence[float],
    L_henry_diag: Sequence[float],
) -> Dict[str, float]:
    """Peak |V| per circuit using the same linspace knots / dt as the planner QP."""
    from .planner import voltages_from_dynamics

    if not i_path.exists():
        raise CoilLimitsError(f"missing measured file for dynamics V peak: {i_path}")
    df = pd.read_csv(i_path)
    if "time" not in df.columns:
        raise CoilLimitsError(f"{i_path.name} missing time column")
    t_src = df["time"].to_numpy(dtype=float)
    times = np.linspace(float(t_start), float(t_end), int(n_knots))
    if float(t_end) <= float(t_start) or int(n_knots) < 2:
        raise CoilLimitsError("invalid planner window/knots for dynamics V peak")
    dt = float(times[1] - times[0])
    I = np.zeros((len(times), len(circuit_order)), dtype=float)
    for j, name in enumerate(circuit_order):
        if name not in df.columns:
            raise CoilLimitsError(f"{i_path.name} missing circuit {name!r}")
        I[:, j] = np.interp(times, t_src, df[name].to_numpy(dtype=float))
    R = np.asarray(R_ohm, dtype=float).reshape(-1)
    L = np.diag(np.asarray(L_henry_diag, dtype=float).reshape(-1))
    if R.shape[0] != len(circuit_order) or L.shape[0] != len(circuit_order):
        raise CoilLimitsError("R/L length mismatch vs circuit_order for dynamics V peak")
    V = voltages_from_dynamics(I, R=R, L=L, dt=dt)
    out: Dict[str, float] = {}
    for j, name in enumerate(circuit_order):
        peak = float(np.max(np.abs(V[:, j])))
        if not np.isfinite(peak) or peak < 0.0:
            raise CoilLimitsError(f"{name}: invalid planner-consistent V peak={peak}")
        # Allow zero only if truly flat; still usable as bound floor via other candidates
        out[str(name)] = peak
    return out


def resolve_measured_peak_limits(
    auth: CoilLimitsAuthority,
    *,
    inputs_dir: Path,
    circuit_order: Sequence[str],
    t_start: float,
    t_end: float,
    R_ohm_by_circuit: Optional[Mapping[str, float]] = None,
    L_henry_by_circuit: Optional[Mapping[str, float]] = None,
    n_knots: int = 21,
) -> CoilLimitsAuthority:
    """Materialize Imax/Vmax = margin_factor × peak|signal| in window (declared policy).

    Imax from peak |measured I|.
    Vmax from margin_factor × max(|V_meas|, ohmic |I|R, planner-consistent |RI+L dI/dt|).
    """
    auth.validate()
    if auth.limit_policy != "measured_peak_margin":
        return auth
    if auth.awaiting:
        raise CoilLimitsError("cannot resolve awaiting coil_limits authority")
    factor = float(auth.margin_factor or 0.0)
    if factor <= 1.0:
        raise CoilLimitsError("margin_factor must be > 1")
    inputs_dir = Path(inputs_dir)
    i_path = inputs_dir / "pf_currents.csv"
    v_path = inputs_dir / "pf_voltages.csv"
    order = [str(c) for c in circuit_order]
    dyn_peaks: Dict[str, float] = {}
    if R_ohm_by_circuit and L_henry_by_circuit and all(
        c in R_ohm_by_circuit and c in L_henry_by_circuit for c in order
    ):
        dyn_peaks = _dynamics_v_peak_planner_consistent(
            i_path,
            order,
            t_start=t_start,
            t_end=t_end,
            n_knots=int(n_knots),
            R_ohm=[float(R_ohm_by_circuit[c]) for c in order],
            L_henry_diag=[float(L_henry_by_circuit[c]) for c in order],
        )
    circuits: Dict[str, CircuitLimit] = {}
    peaks: Dict[str, Any] = {}
    for name in order:
        i_peak = _peak_abs_in_window(i_path, name, t_start, t_end)
        v_candidates: List[tuple[str, float]] = []
        try:
            v_candidates.append(
                ("measured_pf_voltages", _peak_abs_in_window(v_path, name, t_start, t_end))
            )
        except CoilLimitsError:
            pass
        R = None
        if R_ohm_by_circuit is not None and name in R_ohm_by_circuit:
            R = float(R_ohm_by_circuit[name])
        if R is not None and R > 0:
            v_candidates.append(("ohmic_synthetic_IxR", float(i_peak) * R))
        if name in dyn_peaks:
            v_candidates.append(("dynamics_planner_knots", float(dyn_peaks[name])))
        if not v_candidates:
            raise CoilLimitsError(
                f"{name}: cannot resolve V peak — no finite pf_voltages and no cited R/L "
                "for ohmic/dynamics fallback"
            )
        v_source, v_peak = max(v_candidates, key=lambda kv: kv[1])
        imax = factor * i_peak
        vmax = factor * v_peak
        circuits[str(name)] = CircuitLimit(
            Imax_A=imax,
            Vmax_V=vmax,
            Imin_A=-imax,
            Vmin_V=-vmax,
            notes=(
                f"resolved measured_peak_margin: "
                f"Imax={factor:g}*|{i_peak:.6g}|A, "
                f"Vmax={factor:g}*|{v_peak:.6g}|V ({v_source})"
            ),
        )
        peaks[str(name)] = {
            "I_peak_abs_A": i_peak,
            "V_peak_abs_V": v_peak,
            "V_peak_source": v_source,
            "V_peak_candidates": {k: float(v) for k, v in v_candidates},
            "Imax_A": imax,
            "Vmax_V": vmax,
        }
    resolution = {
        "policy": "measured_peak_margin",
        "margin_factor": factor,
        "n_knots": int(n_knots),
        "t_start": float(t_start),
        "t_end": float(t_end),
        "peaks": peaks,
    }
    out = CoilLimitsAuthority(
        authority_name=auth.authority_name,
        authority_version=auth.authority_version,
        status="cited_resolved",
        circuits=circuits,
        citation=auth.citation,
        notes=(
            f"{auth.notes} | resolved from measured_peak_margin "
            f"factor={factor} window=[{t_start:.6g},{t_end:.6g}]"
        ),
        limit_policy="fixed",
        margin_factor=factor,
        resolution=resolution,
        raw=auth.raw,
    )
    out.validate()
    out.require_ready(list(circuit_order))
    return out


def coil_limits_status_line(auth: CoilLimitsAuthority) -> str:
    if auth.awaiting:
        return (
            "[INFO] coil_limits: awaiting_authority — planner blocked until cited "
            "Imax_A/Vmax_V or measured_peak_margin policy (ADR-004)"
        )
    if auth.limit_policy == "measured_peak_margin":
        return (
            f"[OK] coil_limits: measured_peak_margin factor={auth.margin_factor} "
            f"citation={auth.citation!r}"
        )
    return (
        f"[OK] coil_limits: {len(auth.circuits)} circuits "
        f"citation={auth.citation!r}"
    )
