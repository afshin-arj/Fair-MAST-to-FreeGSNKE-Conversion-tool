"""ADR-004 Phase 2: Python GSPulse-style feedforward planner (no MATLAB).

v1 scope (active circuits only):
  - Circuit dynamics V = R I + L dI/dt from FreeGSNKE-built R/M snapshot
  - Global trajectory QP cost: track measured I, penalize V / dI / d²I
  - Box constraints from cited coil_limits_authority (hard gate)
  - Planning residual vs measured / ohmic-synthetic voltages (honesty labels)

Passives deferred until passive_resistivity is no longer awaiting.
GS Picard shape terms deferred to a later increment (shape targets recorded for provenance).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .coil_limits import CoilLimitsAuthority


class PlannerError(RuntimeError):
    pass


def _strict_bool(value: Any, name: str, *, default: Optional[bool] = None) -> bool:
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise PlannerError(f"{name} must be a JSON boolean (got {type(value).__name__})")
    return value


@dataclass(frozen=True)
class PlannerAuthority:
    authority_name: str = "planner"
    authority_version: str = "1.4.0"
    enabled: bool = False
    require: bool = False
    output_relpath: str = "07_planner"
    n_knots: int = 21
    knot_policy: str = "linspace_window_inclusive"
    weight_track_I: float = 1.0
    weight_V: float = 1.0e-6
    weight_dI: float = 1.0e-2
    weight_d2I: float = 1.0e-3
    # Path B2: vacuum-coil Green's isoflux / x-point B (soft-skip if no geometry)
    enable_isoflux: bool = True
    require_isoflux: bool = False
    weight_isoflux: float = 10.0
    weight_xpoint_B: float = 1.0
    isoflux_ref_policy: str = "max_R"
    isoflux_max_control_points: int = 32
    # Path B3: Picard outer loop (forward GS → freeze plasma offsets → re-QP)
    enable_picard: bool = True
    require_picard: bool = False
    max_picard_iterations: int = 2
    picard_rel_tol: float = 1.0e-3
    # Path B4: absolute mean ψ_bry cost
    enable_psi_bry: bool = True
    require_psi_bry: bool = False
    weight_psi_bry: float = 1.0
    qp_solver: str = "projected_iter"
    qp_rel_tol: float = 1.0e-9
    max_qp_iterations: int = 40
    notes: str = ""

    def validate(self) -> None:
        if not self.authority_name.strip():
            raise PlannerError("authority_name required")
        if self.knot_policy != "linspace_window_inclusive":
            raise PlannerError("knot_policy must be linspace_window_inclusive (v1)")
        if not (2 <= int(self.n_knots) <= 500):
            raise PlannerError("n_knots must be in [2, 500]")
        for name in (
            "weight_track_I",
            "weight_V",
            "weight_dI",
            "weight_d2I",
            "weight_isoflux",
            "weight_xpoint_B",
            "weight_psi_bry",
        ):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or float(v) < 0:
                raise PlannerError(f"{name} must be >= 0")
        if self.isoflux_ref_policy not in {"max_R", "first_point"}:
            raise PlannerError("isoflux_ref_policy must be max_R or first_point")
        if not (2 <= int(self.isoflux_max_control_points) <= 512):
            raise PlannerError("isoflux_max_control_points must be in [2, 512]")
        if not (1 <= int(self.max_qp_iterations) <= 500):
            raise PlannerError("max_qp_iterations must be in [1, 500]")
        if self.qp_solver not in {"projected_iter", "slsqp"}:
            raise PlannerError("qp_solver must be projected_iter or slsqp")
        if (
            not isinstance(self.qp_rel_tol, (int, float))
            or not (float(self.qp_rel_tol) > 0.0)
        ):
            raise PlannerError("qp_rel_tol must be > 0")
        if not (0 <= int(self.max_picard_iterations) <= 20):
            raise PlannerError("max_picard_iterations must be in [0, 20]")
        if (
            not isinstance(self.picard_rel_tol, (int, float))
            or not (float(self.picard_rel_tol) > 0.0)
        ):
            raise PlannerError("picard_rel_tol must be > 0")
        if not isinstance(self.enabled, bool) or not isinstance(self.require, bool):
            raise PlannerError("enabled/require must be bool")
        if not isinstance(self.enable_isoflux, bool) or not isinstance(
            self.require_isoflux, bool
        ):
            raise PlannerError("enable_isoflux/require_isoflux must be bool")
        if not isinstance(self.enable_picard, bool) or not isinstance(
            self.require_picard, bool
        ):
            raise PlannerError("enable_picard/require_picard must be bool")
        if not isinstance(self.enable_psi_bry, bool) or not isinstance(
            self.require_psi_bry, bool
        ):
            raise PlannerError("enable_psi_bry/require_psi_bry must be bool")
        if not str(self.output_relpath).strip():
            raise PlannerError("output_relpath required")

    def to_json_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_planner_authority(path: Path) -> PlannerAuthority:
    path = Path(path)
    if not path.exists():
        raise PlannerError(f"planner_authority not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise PlannerError("planner_authority must be a JSON object")
    auth = PlannerAuthority(
        authority_name=str(obj.get("authority_name", "planner")),
        authority_version=str(obj.get("authority_version", "1.4.0")),
        enabled=_strict_bool(obj.get("enabled"), "enabled", default=False),
        require=_strict_bool(obj.get("require"), "require", default=False),
        output_relpath=str(obj.get("output_relpath", "07_planner")),
        n_knots=int(obj.get("n_knots", 21)),
        knot_policy=str(obj.get("knot_policy", "linspace_window_inclusive")),
        weight_track_I=float(obj.get("weight_track_I", 1.0)),
        weight_V=float(obj.get("weight_V", 1.0e-6)),
        weight_dI=float(obj.get("weight_dI", 1.0e-2)),
        weight_d2I=float(obj.get("weight_d2I", 1.0e-3)),
        enable_isoflux=_strict_bool(obj.get("enable_isoflux"), "enable_isoflux", default=True),
        require_isoflux=_strict_bool(
            obj.get("require_isoflux"), "require_isoflux", default=False
        ),
        weight_isoflux=float(obj.get("weight_isoflux", 10.0)),
        weight_xpoint_B=float(obj.get("weight_xpoint_B", 1.0)),
        isoflux_ref_policy=str(obj.get("isoflux_ref_policy", "max_R")),
        isoflux_max_control_points=int(obj.get("isoflux_max_control_points", 32)),
        enable_picard=_strict_bool(obj.get("enable_picard"), "enable_picard", default=True),
        require_picard=_strict_bool(
            obj.get("require_picard"), "require_picard", default=False
        ),
        max_picard_iterations=int(obj.get("max_picard_iterations", 2)),
        picard_rel_tol=float(obj.get("picard_rel_tol", 1.0e-3)),
        enable_psi_bry=_strict_bool(obj.get("enable_psi_bry"), "enable_psi_bry", default=True),
        require_psi_bry=_strict_bool(
            obj.get("require_psi_bry"), "require_psi_bry", default=False
        ),
        weight_psi_bry=float(obj.get("weight_psi_bry", 1.0)),
        qp_solver=str(obj.get("qp_solver", "projected_iter")),
        qp_rel_tol=float(obj.get("qp_rel_tol", 1.0e-9)),
        max_qp_iterations=int(obj.get("max_qp_iterations", 40)),
        notes=str(obj.get("notes", "")),
    )
    auth.validate()
    return auth


def write_planner_authority(inputs_dir: Path, auth: PlannerAuthority) -> Path:
    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "planner_authority"
    root.mkdir(parents=True, exist_ok=True)
    auth.validate()
    path = root / "planner_authority.json"
    path.write_text(json.dumps(auth.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


@dataclass
class CircuitDynamics:
    circuit_order: List[str]
    R_ohm: np.ndarray  # (n,)
    L_henry: np.ndarray  # (n, n) mutual inductance (coil_self_ind active block)
    source: str
    notes: str = ""
    # Structured provenance from circuit_dynamics_authority fill (preferred over note substrings).
    fill_notes: Optional[Dict[str, Any]] = None

    def validate(self) -> None:
        n = len(self.circuit_order)
        if n < 1:
            raise PlannerError("circuit_order empty")
        R = np.asarray(self.R_ohm, dtype=float).reshape(-1)
        L = np.asarray(self.L_henry, dtype=float)
        if R.shape != (n,):
            raise PlannerError(f"R shape {R.shape} != ({n},)")
        if L.shape != (n, n):
            raise PlannerError(f"L shape {L.shape} != ({n}, {n})")
        if not np.all(np.isfinite(R)) or not np.all(R > 0):
            raise PlannerError("R must be finite and > 0")
        if not np.all(np.isfinite(L)):
            raise PlannerError("L must be finite")
        # Symmetry check (tolerance)
        if float(np.max(np.abs(L - L.T))) > 1e-6 * max(1.0, float(np.max(np.abs(L)))):
            raise PlannerError("L must be symmetric within tolerance")

    def to_json_dict(self) -> Dict[str, Any]:
        self.validate()
        out: Dict[str, Any] = {
            "circuit_order": list(self.circuit_order),
            "R_ohm": np.asarray(self.R_ohm, dtype=float).tolist(),
            "L_henry": np.asarray(self.L_henry, dtype=float).tolist(),
            "source": self.source,
            "notes": self.notes,
        }
        if self.fill_notes is not None:
            out["fill_notes"] = dict(self.fill_notes)
        return out


def mutuals_honesty_label(
    *,
    source: str = "",
    notes: str = "",
    fill_notes: Optional[Dict[str, Any]] = None,
) -> str:
    """Prefer structured fill_notes['mutuals'] / exact mutuals= token over substring match."""
    import re

    if isinstance(fill_notes, dict):
        m = fill_notes.get("mutuals")
        if isinstance(m, str) and m.strip() and m.strip() != "unknown":
            return m.strip()
    # Prefer the last exact mutuals=<token> (authority fill appends the declared value last).
    tokens = re.findall(r"(?:^|[|\s;])mutuals=([^\s|;]+)", str(notes or ""))
    if tokens:
        return tokens[-1]
    src_l = str(source or "").lower()
    if "mutuals_neglected" in src_l:
        return "neglected_diagonal_self_only_declared"
    if "prefer_freegsnke_mutuals" in src_l or "freegsnke_offdiag" in src_l:
        return "freegsnke_offdiag_retained_cited_Lii_overlay"
    if "freegsnke" in src_l:
        return "freegsnke_active_block"
    return "unknown"


def residual_compare_class(drive_label: str) -> str:
    """Tag residual rows so deferred ohmic V is not read as a failed measured-V fit."""
    lab = str(drive_label or "")
    if lab == "measured_fairmast_V":
        return "measured_V"
    if lab == "ohmic_synthetic_IxR":
        return "deferred_ohmic_synthetic"
    if lab in ("unknown", ""):
        return "unknown"
    return f"other:{lab}"


def load_circuit_dynamics(path: Path) -> CircuitDynamics:
    path = Path(path)
    if not path.exists():
        raise PlannerError(f"circuit_dynamics snapshot not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    fill = obj.get("fill_notes")
    dyn = CircuitDynamics(
        circuit_order=[str(x) for x in obj["circuit_order"]],
        R_ohm=np.asarray(obj["R_ohm"], dtype=float),
        L_henry=np.asarray(obj["L_henry"], dtype=float),
        source=str(obj.get("source", "")),
        notes=str(obj.get("notes", "")),
        fill_notes=dict(fill) if isinstance(fill, dict) else None,
    )
    dyn.validate()
    return dyn


def write_circuit_dynamics(path: Path, dyn: CircuitDynamics) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dyn.validate()
    path.write_text(json.dumps(dyn.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def extract_circuit_dynamics_from_freegsnke_machine(
    *,
    machine_dir: Path,
    circuit_order: Sequence[str],
    freegsnke_python: Optional[str] = None,
) -> CircuitDynamics:
    """Build R and L via FreeGSNKE machine_config (active block only).

    Runs in-process if freegsnke is importable; otherwise raises with fix hint
    (use freegsnke_python env / snapshot from a prior extract).
    """
    machine_dir = Path(machine_dir)
    try:
        from freegsnke import build_machine  # type: ignore
        from freegsnke import machine_config  # type: ignore
    except Exception as e:
        raise PlannerError(
            "freegsnke not importable in this interpreter — extract circuit dynamics "
            "with freegsnke_python or provide inputs/circuit_dynamics_snapshot.json. "
            f"Import error: {type(e).__name__}: {e}"
        ) from e

    tokamak = build_machine.tokamak(
        active_coils_path=str(machine_dir / "active_coils.pickle"),
        passive_coils_path=str(machine_dir / "passive_coils.pickle"),
        limiter_path=str(machine_dir / "limiter.pickle"),
        wall_path=str(machine_dir / "wall.pickle"),
    )
    # Ensure R/M built (idempotent if already present)
    if not (hasattr(tokamak, "coil_resist") and hasattr(tokamak, "coil_self_ind")):
        machine_config.build_tokamak_R_and_M(tokamak)

    names = []
    for name, coil in getattr(tokamak, "coils", []):
        if hasattr(coil, "control") and coil.control:
            names.append(str(name))
    order = [str(c) for c in circuit_order]
    if names != order:
        raise PlannerError(
            "machine control coil order does not match voltage_map order.\n"
            f"  machine: {names}\n  map: {order}"
        )
    # Active block: FreeGSNKE stores actives first
    n = len(order)
    R_all = np.asarray(tokamak.coil_resist, dtype=float)
    L_all = np.asarray(tokamak.coil_self_ind, dtype=float)
    if R_all.shape[0] < n or L_all.shape[0] < n:
        raise PlannerError("tokamak R/L smaller than active circuit count")
    dyn = CircuitDynamics(
        circuit_order=order,
        R_ohm=R_all[:n].copy(),
        L_henry=L_all[:n, :n].copy(),
        source="freegsnke.machine_config.build_tokamak_R_and_M(active_block)",
        notes="Active-only block; passives excluded while passive_resistivity awaiting_authority.",
    )
    dyn.validate()
    return dyn


def _interp_matrix(t_query: np.ndarray, t_src: np.ndarray, Y: np.ndarray) -> np.ndarray:
    """Y shape (n_time, n_col) → interpolate each column at t_query (no extrapolation)."""
    out = np.zeros((len(t_query), Y.shape[1]), dtype=float)
    for j in range(Y.shape[1]):
        out[:, j] = np.interp(t_query, t_src, Y[:, j])
    return out


def _require_window_covered(
    *,
    t_query: np.ndarray,
    t_src: np.ndarray,
    label: str,
    atol: float = 1e-9,
) -> None:
    """Fail-closed if planner knots fall outside measured PF time coverage."""
    if t_src.size < 2:
        raise PlannerError(f"{label}: need >= 2 time samples")
    t0 = float(np.min(t_src))
    t1 = float(np.max(t_src))
    q0 = float(np.min(t_query))
    q1 = float(np.max(t_query))
    if q0 < t0 - atol or q1 > t1 + atol:
        raise PlannerError(
            f"{label}: planner window [{q0:.6g},{q1:.6g}] not covered by measured "
            f"time [{t0:.6g},{t1:.6g}] (no silent extrapolation)"
        )


def _load_pf_matrix(inputs_dir: Path, filename: str, circuit_order: Sequence[str]) -> Tuple[np.ndarray, np.ndarray]:
    path = Path(inputs_dir) / filename
    if not path.exists():
        raise PlannerError(f"missing {filename} under inputs/")
    df = pd.read_csv(path)
    if "time" not in df.columns:
        raise PlannerError(f"{filename} missing time column")
    missing = [c for c in circuit_order if c not in df.columns]
    if missing:
        raise PlannerError(f"{filename} missing circuits: {missing}")
    t = df["time"].to_numpy(dtype=float)
    Y = np.column_stack([df[c].to_numpy(dtype=float) for c in circuit_order])
    return t, Y


def voltages_from_dynamics(
    I: np.ndarray,
    *,
    R: np.ndarray,
    L: np.ndarray,
    dt: float,
) -> np.ndarray:
    """V_k = R I_k + L (I_{k+1}-I_k)/dt with last step backward difference."""
    I = np.asarray(I, dtype=float)
    n_t, n = I.shape
    if n_t < 2:
        raise PlannerError("need >= 2 time knots for dI/dt")
    if not (dt > 0):
        raise PlannerError("dt must be > 0")
    V = np.zeros_like(I)
    dI = np.diff(I, axis=0) / float(dt)
    for k in range(n_t - 1):
        V[k] = R * I[k] + L @ dI[k]
    V[-1] = R * I[-1] + L @ dI[-1]
    return V


def _finite_rms(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    a = np.asarray(a, dtype=float).reshape(-1)
    b = np.asarray(b, dtype=float).reshape(-1)
    mask = np.isfinite(a) & np.isfinite(b)
    if int(np.count_nonzero(mask)) < 1:
        return None
    d = a[mask] - b[mask]
    return float(np.sqrt(np.mean(d * d)))


def _finite_corr(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    a = np.asarray(a, dtype=float).reshape(-1)
    b = np.asarray(b, dtype=float).reshape(-1)
    mask = np.isfinite(a) & np.isfinite(b)
    if int(np.count_nonzero(mask)) < 3:
        return None
    aa, bb = a[mask], b[mask]
    if float(np.std(aa)) < 1e-18 or float(np.std(bb)) < 1e-18:
        return None
    return float(np.corrcoef(aa, bb)[0, 1])


def _classify_voltage_gap_status(
    *,
    drive_label: str,
    i_track_rms_A: Optional[float],
    rms_plan_minus_meas_V: Optional[float],
    rms_plan_minus_dyn_V: Optional[float],
    corr_dyn_meas: Optional[float],
    corr_dyn_neg_meas: Optional[float],
) -> str:
    """Declared gap status — never invents voltage_map signs."""
    if drive_label == "ohmic_synthetic_IxR":
        return "deferred_ohmic_ixr"
    if (
        corr_dyn_meas is not None
        and corr_dyn_neg_meas is not None
        and float(corr_dyn_meas) < -0.7
        and float(corr_dyn_neg_meas) > 0.7
    ):
        return "polarity_suspect"
    if (
        rms_plan_minus_dyn_V is not None
        and rms_plan_minus_meas_V is not None
        and float(rms_plan_minus_meas_V) > 1.0
        and float(rms_plan_minus_dyn_V) <= 0.25 * float(rms_plan_minus_meas_V)
    ):
        return "model_gap_expected"
    if i_track_rms_A is not None and np.isfinite(i_track_rms_A):
        return "i_track_ok"
    return "unknown"


def build_voltage_model_gap(
    *,
    circuit_order: Sequence[str],
    drive_labels: Dict[str, str],
    I_plan: np.ndarray,
    I_meas: np.ndarray,
    V_plan: np.ndarray,
    V_obs: np.ndarray,
    V_dyn: np.ndarray,
    V_IxR: np.ndarray,
    R_ohm: np.ndarray,
) -> Dict[str, Any]:
    """Decompose planned-vs-measured V into I-track + dynamics model gap + polarity.

    Large ΔV with tiny rms(V_plan−V_dyn) means the QP I-plan is fine; terminal V is
    outside the active-only plant model (or polarity convention is suspect).
    """
    order = [str(c) for c in circuit_order]
    R = np.asarray(R_ohm, dtype=float).reshape(-1)
    circuits: List[Dict[str, Any]] = []
    n_polarity = 0
    n_model_gap = 0
    i_track_vals: List[float] = []
    for i, c in enumerate(order):
        dlab = str(drive_labels.get(c) or "unknown")
        i_rms = _finite_rms(I_plan[:, i], I_meas[:, i])
        if i_rms is not None:
            i_track_vals.append(float(i_rms))
        rms_plan_meas = _finite_rms(V_plan[:, i], V_obs[:, i])
        rms_dyn_meas = _finite_rms(V_dyn[:, i], V_obs[:, i])
        rms_plan_dyn = _finite_rms(V_plan[:, i], V_dyn[:, i])
        rms_plan_ixr = _finite_rms(V_plan[:, i], V_IxR[:, i])
        corr_dm = _finite_corr(V_dyn[:, i], V_obs[:, i])
        corr_dnm = _finite_corr(V_dyn[:, i], -np.asarray(V_obs[:, i], dtype=float))
        status = _classify_voltage_gap_status(
            drive_label=dlab,
            i_track_rms_A=i_rms,
            rms_plan_minus_meas_V=rms_plan_meas,
            rms_plan_minus_dyn_V=rms_plan_dyn,
            corr_dyn_meas=corr_dm,
            corr_dyn_neg_meas=corr_dnm,
        )
        if status == "polarity_suspect":
            n_polarity += 1
        if status == "model_gap_expected":
            n_model_gap += 1
        circuits.append(
            {
                "circuit": c,
                "drive_label": dlab,
                "residual_compare_class": residual_compare_class(dlab),
                "R_ohm_cited": float(R[i]) if i < R.size else None,
                "i_track_rms_A": i_rms,
                "rms_plan_minus_meas_V": rms_plan_meas,
                "rms_dyn_minus_meas_V": rms_dyn_meas,
                "rms_plan_minus_dyn_V": rms_plan_dyn,
                "rms_plan_minus_IxR_V": rms_plan_ixr,
                "corr_dyn_meas": corr_dm,
                "corr_dyn_neg_meas": corr_dnm,
                "gap_status": status,
            }
        )
    mean_i = float(np.mean(i_track_vals)) if i_track_vals else None
    overall = "ok"
    if n_polarity > 0:
        overall = "polarity_suspect"
    elif n_model_gap > 0:
        overall = "model_gap_expected"
    return {
        "version": "1.0",
        "overall_status": overall,
        "n_polarity_suspect": int(n_polarity),
        "n_model_gap_expected": int(n_model_gap),
        "mean_i_track_rms_A": mean_i,
        "circuits": circuits,
        "note": (
            "Planned V = R I + L dI/dt (I-primary QP). "
            "rms_plan_minus_dyn ≪ rms_plan_minus_meas ⇒ model/terminal-V gap, not failed I-plan. "
            "polarity_suspect: corr(V_dyn,V_meas)<−0.7 and corr(V_dyn,−V_meas)>0.7 — "
            "YELLOW only; do not auto-flip voltage_map without citation. "
            "deferred_ohmic_ixr uses cited circuit_dynamics R (not invented); "
            "evolutive ohmic fill may still use FreeGSNKE coil_resist (dual-R honesty)."
        ),
        "do_not": [
            "auto_flip_voltage_map_sign",
            "invent_passive_resistivity",
            "invent_P3_P6_measured_V",
        ],
    }


def solve_trajectory_qp(
    *,
    I_target: np.ndarray,
    R: np.ndarray,
    L: np.ndarray,
    dt: float,
    I_lo: np.ndarray,
    I_hi: np.ndarray,
    V_lo: np.ndarray,
    V_hi: np.ndarray,
    weight_track_I: float,
    weight_V: float,
    weight_dI: float,
    weight_d2I: float,
    max_iterations: int = 40,
    isoflux_pack: Optional[Dict[str, Any]] = None,
    weight_isoflux: float = 0.0,
    weight_xpoint_B: float = 0.0,
    weight_psi_bry: float = 0.0,
) -> Dict[str, Any]:
    """Projected trajectory optimizer (numpy-only GSPulse-inspired cost).

    Decision variable: I[t, circuit]. Voltages follow circuit dynamics.
    Optional Path B2/B4 vacuum isoflux / x-point B / ψ_bry sensors: per-knot linear
    ``y = G @ I`` with Tikhonov blend against current-tracking.
    """
    I_target = np.asarray(I_target, dtype=float)
    n_t, n = I_target.shape
    R = np.asarray(R, dtype=float).reshape(n)
    L = np.asarray(L, dtype=float).reshape(n, n)
    I = np.clip(I_target.copy(), I_lo, I_hi)
    wI = float(weight_track_I)
    wV = float(weight_V)
    w1 = float(weight_dI)
    w2 = float(weight_d2I)
    w_iso = float(weight_isoflux)
    w_xp = float(weight_xpoint_B)
    w_psi = float(weight_psi_bry)
    knots = (isoflux_pack or {}).get("knots") if isinstance(isoflux_pack, dict) else None

    def _shape_pull(k: int, I_k: np.ndarray) -> np.ndarray:
        """Tikhonov blend of tracking vector with vacuum sensor least-squares."""
        if not knots or k >= len(knots):
            return I_k
        entry = knots[k]
        if not isinstance(entry, dict):
            return I_k
        A = wI * np.eye(n)
        b = wI * I_k
        used = False
        for key, w in (
            ("isoflux", w_iso),
            ("xpoint_B", w_xp),
            ("psi_bry", w_psi),
        ):
            sens = entry.get(key)
            if w > 0 and sens is not None and hasattr(sens, "G"):
                G = np.asarray(sens.G, dtype=float)
                y = np.asarray(sens.target, dtype=float).ravel()
                if G.ndim == 2 and G.shape[1] == n and G.shape[0] == y.size:
                    A = A + w * (G.T @ G)
                    b = b + w * (G.T @ y)
                    used = True
        if not used:
            return I_k
        try:
            return np.linalg.solve(A, b)
        except np.linalg.LinAlgError:
            return np.linalg.lstsq(A, b, rcond=None)[0]

    hist_cost: List[float] = []
    for _it in range(int(max_iterations)):
        I_new = I.copy()
        for k in range(n_t):
            acc = wI * I_target[k]
            wsum = wI
            if k > 0:
                acc = acc + w1 * I[k - 1]
                wsum += w1
            if k + 1 < n_t:
                acc = acc + w1 * I[k + 1]
                wsum += w1
            if k > 1:
                acc = acc + w2 * (2.0 * I[k - 1] - I[k - 2])
                wsum += w2
            if k + 2 < n_t:
                acc = acc + w2 * (2.0 * I[k + 1] - I[k + 2])
                wsum += w2
            I_track = acc / max(wsum, 1e-30)
            I_new[k] = _shape_pull(k, I_track)
        I_new = np.clip(I_new, I_lo, I_hi)
        V = voltages_from_dynamics(I_new, R=R, L=L, dt=dt)
        over = (V > V_hi) | (V < V_lo)
        if np.any(over):
            for k in range(n_t):
                for j in range(n):
                    if not over[k, j]:
                        continue
                    if k > 0:
                        I_new[k, j] = 0.5 * (I_new[k, j] + I_new[k - 1, j])
                    elif k + 1 < n_t:
                        I_new[k, j] = 0.5 * (I_new[k, j] + I_new[k + 1, j])
            I_new = np.clip(I_new, I_lo, I_hi)
            V = voltages_from_dynamics(I_new, R=R, L=L, dt=dt)
        if wV > 0.0:
            I_new = np.clip((1.0 - 1e-3 * wV) * I_new + (1e-3 * wV) * I_target, I_lo, I_hi)
            V = voltages_from_dynamics(I_new, R=R, L=L, dt=dt)

        dI = np.diff(I_new, axis=0)
        d2 = np.diff(dI, axis=0) if n_t > 2 else np.zeros((0, n))
        cost = (
            wI * float(np.mean((I_new - I_target) ** 2))
            + wV * float(np.mean(V**2))
            + w1 * float(np.mean(dI**2))
            + (w2 * float(np.mean(d2**2)) if d2.size else 0.0)
        )
        hist_cost.append(cost)
        if float(np.max(np.abs(I_new - I))) < 1e-9 * max(1.0, float(np.max(np.abs(I_target)))):
            I = I_new
            break
        I = I_new

    V = voltages_from_dynamics(I, R=R, L=L, dt=dt)
    viol = (V > V_hi) | (V < V_lo)
    return {
        "I": I,
        "V": V,
        "cost_history": hist_cost,
        "n_voltage_violations_raw": int(np.sum(viol)),
        "voltage_violation_mask": viol,
        "qp_solver": "projected_iter",
    }


def _trajectory_cost(
    I: np.ndarray,
    *,
    I_target: np.ndarray,
    R: np.ndarray,
    L: np.ndarray,
    dt: float,
    weight_track_I: float,
    weight_V: float,
    weight_dI: float,
    weight_d2I: float,
    isoflux_pack: Optional[Dict[str, Any]] = None,
    weight_isoflux: float = 0.0,
    weight_xpoint_B: float = 0.0,
    weight_psi_bry: float = 0.0,
) -> float:
    """Scalar cost shared by projected_iter and SLSQP solvers."""
    n_t, n = I.shape
    V = voltages_from_dynamics(I, R=R, L=L, dt=dt)
    wI = float(weight_track_I)
    wV = float(weight_V)
    w1 = float(weight_dI)
    w2 = float(weight_d2I)
    dI = np.diff(I, axis=0)
    d2 = np.diff(dI, axis=0) if n_t > 2 else np.zeros((0, n))
    cost = (
        wI * float(np.mean((I - I_target) ** 2))
        + wV * float(np.mean(V**2))
        + w1 * float(np.mean(dI**2))
        + (w2 * float(np.mean(d2**2)) if d2.size else 0.0)
    )
    knots = (isoflux_pack or {}).get("knots") if isinstance(isoflux_pack, dict) else None
    if knots:
        for k in range(min(len(knots), n_t)):
            entry = knots[k]
            if not isinstance(entry, dict):
                continue
            I_k = I[k]
            for key, w in (
                ("isoflux", float(weight_isoflux)),
                ("xpoint_B", float(weight_xpoint_B)),
                ("psi_bry", float(weight_psi_bry)),
            ):
                if w <= 0:
                    continue
                sens = entry.get(key)
                if sens is None or not hasattr(sens, "G"):
                    continue
                G = np.asarray(sens.G, dtype=float)
                y = np.asarray(sens.target, dtype=float).ravel()
                if G.ndim == 2 and G.shape[1] == n and G.shape[0] == y.size:
                    resid = G @ I_k - y
                    cost += w * float(np.mean(resid**2))
    return cost


def solve_trajectory_slsqp(
    *,
    I_target: np.ndarray,
    R: np.ndarray,
    L: np.ndarray,
    dt: float,
    I_lo: np.ndarray,
    I_hi: np.ndarray,
    V_lo: np.ndarray,
    V_hi: np.ndarray,
    weight_track_I: float,
    weight_V: float,
    weight_dI: float,
    weight_d2I: float,
    max_iterations: int = 40,
    rel_tol: float = 1.0e-9,
    isoflux_pack: Optional[Dict[str, Any]] = None,
    weight_isoflux: float = 0.0,
    weight_xpoint_B: float = 0.0,
    weight_psi_bry: float = 0.0,
) -> Dict[str, Any]:
    """SLSQP box-constrained trajectory optimizer (scipy)."""
    from scipy.optimize import minimize

    I_target = np.asarray(I_target, dtype=float)
    n_t, n = I_target.shape
    R = np.asarray(R, dtype=float).reshape(n)
    L = np.asarray(L, dtype=float).reshape(n, n)
    I_lo = np.asarray(I_lo, dtype=float).reshape(n)
    I_hi = np.asarray(I_hi, dtype=float).reshape(n)
    V_lo = np.asarray(V_lo, dtype=float).reshape(n)
    V_hi = np.asarray(V_hi, dtype=float).reshape(n)
    x0 = np.clip(I_target.copy(), I_lo, I_hi).ravel()
    bounds = [(float(I_lo[j]), float(I_hi[j])) for _ in range(n_t) for j in range(n)]

    def _unpack(x: np.ndarray) -> np.ndarray:
        return np.asarray(x, dtype=float).reshape(n_t, n)

    def objective(x: np.ndarray) -> float:
        return _trajectory_cost(
            _unpack(x),
            I_target=I_target,
            R=R,
            L=L,
            dt=dt,
            weight_track_I=weight_track_I,
            weight_V=weight_V,
            weight_dI=weight_dI,
            weight_d2I=weight_d2I,
            isoflux_pack=isoflux_pack,
            weight_isoflux=weight_isoflux,
            weight_xpoint_B=weight_xpoint_B,
            weight_psi_bry=weight_psi_bry,
        )

    res = minimize(
        objective,
        x0,
        method="SLSQP",
        bounds=bounds,
        options={"maxiter": int(max_iterations), "ftol": float(rel_tol)},
    )
    I = np.clip(_unpack(res.x), I_lo, I_hi)
    V = voltages_from_dynamics(I, R=R, L=L, dt=dt)
    viol = (V > V_hi) | (V < V_lo)
    return {
        "I": I,
        "V": V,
        "cost_history": [float(res.fun)],
        "n_voltage_violations_raw": int(np.sum(viol)),
        "voltage_violation_mask": viol,
        "qp_solver": "slsqp",
        "slsqp_success": bool(res.success),
        "slsqp_message": str(res.message),
    }


def solve_trajectory(
    *,
    qp_solver: str = "projected_iter",
    qp_rel_tol: float = 1.0e-9,
    I_target: np.ndarray,
    R: np.ndarray,
    L: np.ndarray,
    dt: float,
    I_lo: np.ndarray,
    I_hi: np.ndarray,
    V_lo: np.ndarray,
    V_hi: np.ndarray,
    weight_track_I: float,
    weight_V: float,
    weight_dI: float,
    weight_d2I: float,
    max_iterations: int = 40,
    isoflux_pack: Optional[Dict[str, Any]] = None,
    weight_isoflux: float = 0.0,
    weight_xpoint_B: float = 0.0,
    weight_psi_bry: float = 0.0,
) -> Dict[str, Any]:
    """Dispatch trajectory optimizer (projected_iter default, optional SLSQP)."""
    solver = str(qp_solver or "projected_iter").strip().lower()
    kw = dict(
        I_target=I_target,
        R=R,
        L=L,
        dt=dt,
        I_lo=I_lo,
        I_hi=I_hi,
        V_lo=V_lo,
        V_hi=V_hi,
        weight_track_I=weight_track_I,
        weight_V=weight_V,
        weight_dI=weight_dI,
        weight_d2I=weight_d2I,
        max_iterations=max_iterations,
        isoflux_pack=isoflux_pack,
        weight_isoflux=weight_isoflux,
        weight_xpoint_B=weight_xpoint_B,
        weight_psi_bry=weight_psi_bry,
    )
    if solver == "slsqp":
        return solve_trajectory_slsqp(**kw, rel_tol=qp_rel_tol)
    if solver in {"projected_iter", "projected", "default"}:
        return solve_trajectory_qp(**kw)
    raise PlannerError(f"qp_solver must be projected_iter or slsqp (got {qp_solver!r})")


def run_planner_stage(
    *,
    run_dir: Path,
    inputs_dir: Path,
    machine_dir: Path,
    planner_auth: PlannerAuthority,
    coil_limits: CoilLimitsAuthority,
    circuit_order: Sequence[str],
    t_start: float,
    t_end: float,
    shot: Optional[int] = None,
    circuit_dynamics: Optional[CircuitDynamics] = None,
    shape_targets: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Execute planner → write 07_planner/ artifacts. Fail-closed on limits."""
    planner_auth.validate()
    order = [str(c) for c in circuit_order]
    coil_limits.require_ready(order)

    if circuit_dynamics is None:
        snap = Path(inputs_dir) / "circuit_dynamics_snapshot.json"
        if snap.exists():
            circuit_dynamics = load_circuit_dynamics(snap)
        else:
            circuit_dynamics = extract_circuit_dynamics_from_freegsnke_machine(
                machine_dir=machine_dir,
                circuit_order=order,
            )
            write_circuit_dynamics(snap, circuit_dynamics)
    else:
        write_circuit_dynamics(Path(inputs_dir) / "circuit_dynamics_snapshot.json", circuit_dynamics)

    if circuit_dynamics.circuit_order != order:
        raise PlannerError("circuit_dynamics order mismatch vs voltage_map")

    t_I, I_src = _load_pf_matrix(inputs_dir, "pf_currents.csv", order)
    t_V, V_meas = _load_pf_matrix(inputs_dir, "pf_voltages.csv", order)

    n_k = int(planner_auth.n_knots)
    times = np.linspace(float(t_start), float(t_end), n_k)
    if float(t_end) <= float(t_start):
        raise PlannerError("require t_end > t_start")
    dt = float(times[1] - times[0])
    _require_window_covered(t_query=times, t_src=t_I, label="pf_currents.csv")
    _require_window_covered(t_query=times, t_src=t_V, label="pf_voltages.csv")
    I_tgt = _interp_matrix(times, t_I, I_src)
    V_obs = _interp_matrix(times, t_V, V_meas)

    n = len(order)
    I_lo = np.zeros(n, dtype=float)
    I_hi = np.zeros(n, dtype=float)
    V_lo = np.zeros(n, dtype=float)
    V_hi = np.zeros(n, dtype=float)
    for j, name in enumerate(order):
        lim = coil_limits.circuits[name]
        I_lo[j], I_hi[j] = lim.i_bounds()
        V_lo[j], V_hi[j] = lim.v_bounds()

    # Path B2: vacuum-coil Green's isoflux / x-point B (soft-skip unless require_isoflux)
    isoflux_pack: Optional[Dict[str, Any]] = None
    isoflux_used = False
    isoflux_status = "disabled"
    isoflux_note = "enable_isoflux=false"
    if planner_auth.enable_isoflux:
        st_payload = shape_targets
        if st_payload is None:
            st_path = Path(inputs_dir) / "shape_targets_authority" / "shape_targets.json"
            if st_path.is_file():
                try:
                    st_payload = json.loads(st_path.read_text(encoding="utf-8"))
                except Exception:
                    st_payload = None
        try:
            from .planner_isoflux import build_isoflux_sensors_for_knots

            isoflux_pack = build_isoflux_sensors_for_knots(
                machine_dir=Path(machine_dir),
                circuit_order=order,
                shape_targets=st_payload if isinstance(st_payload, dict) else {},
                ref_policy=planner_auth.isoflux_ref_policy,
                max_control_points=int(planner_auth.isoflux_max_control_points),
            )
            isoflux_status = str(isoflux_pack.get("status") or "unknown")
            isoflux_note = str(isoflux_pack.get("note") or "")
            isoflux_used = bool(isoflux_pack.get("ok"))
        except Exception as e:
            isoflux_pack = None
            isoflux_status = "failed"
            isoflux_note = f"{type(e).__name__}: {e}"
            isoflux_used = False
            if planner_auth.require_isoflux:
                raise PlannerError(
                    f"require_isoflux=true but isoflux build failed: {isoflux_note}"
                ) from e
        if planner_auth.require_isoflux and not isoflux_used:
            raise PlannerError(
                f"require_isoflux=true but status={isoflux_status!r}: {isoflux_note}"
            )

    # Path B4: ψ_bry absolute mean-flux targets (soft-skip unless require_psi_bry)
    psi_bry_used = False
    psi_bry_status = "disabled"
    psi_bry_note = "enable_psi_bry=false"
    psi_bry_mode = None
    plasma_inventory: Dict[str, Any] = {}
    psi_bry_payload: Dict[str, Any] = {}
    if planner_auth.enable_psi_bry:
        try:
            from .planner_plasma_scalars import (
                attach_psi_bry_sensors,
                build_psi_bry_targets,
                inventory_plasma_drive,
                load_plasma_scalars_authority,
                write_plasma_scalars_authority,
            )

            ps_path = Path(inputs_dir) / "plasma_scalars_authority" / "plasma_scalars_authority.json"
            if not ps_path.is_file():
                # Prefer shipped config next to repo if snapshotted path missing
                repo_ps = Path(__file__).resolve().parents[2] / "configs" / "plasma_scalars_authority.json"
                if repo_ps.is_file():
                    ps_auth = load_plasma_scalars_authority(repo_ps)
                    write_plasma_scalars_authority(Path(inputs_dir), ps_auth)
                else:
                    raise PlannerError(
                        "plasma_scalars_authority missing — ship configs/plasma_scalars_authority.json"
                    )
            else:
                ps_auth = load_plasma_scalars_authority(ps_path)
            write_plasma_scalars_authority(Path(inputs_dir), ps_auth)
            plasma_inventory = inventory_plasma_drive(
                inputs_dir=Path(inputs_dir), times=times, auth=ps_auth
            )
            st_for_psi = shape_targets
            if st_for_psi is None:
                st_path2 = Path(inputs_dir) / "shape_targets_authority" / "shape_targets.json"
                if st_path2.is_file():
                    try:
                        st_for_psi = json.loads(st_path2.read_text(encoding="utf-8"))
                    except Exception:
                        st_for_psi = None
            cache_guess = Path(cache_dir) if cache_dir is not None else None
            if cache_guess is None or not cache_guess.is_dir():
                for cand in (
                    Path(run_dir) / "cache",
                    Path(inputs_dir).parent / "cache",
                ):
                    if cand.is_dir():
                        cache_guess = cand
                        break
            psi_bry_payload = build_psi_bry_targets(
                times=times,
                auth=ps_auth,
                shape_targets=st_for_psi if isinstance(st_for_psi, dict) else None,
                cache_dir=cache_guess if cache_guess is not None and cache_guess.is_dir() else None,
                inputs_dir=Path(inputs_dir),
            )
            psi_bry_status = str(psi_bry_payload.get("status") or "unknown")
            psi_bry_note = str(psi_bry_payload.get("note") or "")
            psi_bry_mode = psi_bry_payload.get("mode")
            if psi_bry_payload.get("ok") and psi_bry_payload.get("psi_bry_Wb"):
                if isoflux_pack is None or not isoflux_used:
                    psi_bry_status = "skipped_no_isoflux_geometry"
                    psi_bry_note = "ψ_bry sensors need LCFS Green's geometry from Path B2"
                else:
                    isoflux_pack = attach_psi_bry_sensors(
                        isoflux_pack,
                        psi_bry_Wb=psi_bry_payload["psi_bry_Wb"],
                    )
                    psi_bry_used = int(isoflux_pack.get("psi_bry_sensors") or 0) > 0
                    if not psi_bry_used:
                        psi_bry_status = "skipped_no_geometry"
                        psi_bry_note = "no LCFS control points to attach mean-flux sensors"
                    else:
                        psi_bry_status = "ok"
            (Path(run_dir) / planner_auth.output_relpath).mkdir(parents=True, exist_ok=True)
            (Path(run_dir) / planner_auth.output_relpath / "plasma_scalars.json").write_text(
                json.dumps(
                    {
                        "inventory": plasma_inventory,
                        "psi_bry": {
                            "used": psi_bry_used,
                            "status": psi_bry_status,
                            "mode": psi_bry_mode,
                            "note": psi_bry_note,
                            "psi_convention": psi_bry_payload.get("psi_convention"),
                            "var_used": psi_bry_payload.get("var_used"),
                            "attempts": psi_bry_payload.get("attempts"),
                            "psi_bry_Wb": psi_bry_payload.get("psi_bry_Wb"),
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except Exception as e:
            psi_bry_status = "failed"
            psi_bry_note = f"{type(e).__name__}: {e}"
            psi_bry_used = False
            if planner_auth.require_psi_bry:
                raise PlannerError(
                    f"require_psi_bry=true but failed: {psi_bry_note}"
                ) from e
        if planner_auth.require_psi_bry and not psi_bry_used:
            raise PlannerError(
                f"require_psi_bry=true but status={psi_bry_status!r}: {psi_bry_note}"
            )

    sol = solve_trajectory(
        qp_solver=planner_auth.qp_solver,
        qp_rel_tol=planner_auth.qp_rel_tol,
        I_target=I_tgt,
        R=circuit_dynamics.R_ohm,
        L=circuit_dynamics.L_henry,
        dt=dt,
        I_lo=I_lo,
        I_hi=I_hi,
        V_lo=V_lo,
        V_hi=V_hi,
        weight_track_I=planner_auth.weight_track_I,
        weight_V=planner_auth.weight_V,
        weight_dI=planner_auth.weight_dI,
        weight_d2I=planner_auth.weight_d2I,
        max_iterations=planner_auth.max_qp_iterations,
        isoflux_pack=isoflux_pack if isoflux_used or psi_bry_used else None,
        weight_isoflux=planner_auth.weight_isoflux if isoflux_used else 0.0,
        weight_xpoint_B=planner_auth.weight_xpoint_B if isoflux_used else 0.0,
        weight_psi_bry=planner_auth.weight_psi_bry if psi_bry_used else 0.0,
    )
    I_plan = sol["I"]

    # Path B3: Picard outer loop (soft-skip unless require_picard)
    picard_used = False
    picard_status = "disabled"
    picard_note = "enable_picard=false"
    picard_mode = None
    picard_history: List[Any] = []
    picard_converged = False
    picard_rel_tol_used = float(planner_auth.picard_rel_tol)
    if planner_auth.enable_picard:
        if not isoflux_used or isoflux_pack is None:
            picard_status = "skipped_no_isoflux"
            picard_note = "Picard requires isoflux sensors (Path B2); soft-skip"
            if planner_auth.require_picard:
                raise PlannerError(
                    f"require_picard=true but {picard_status}: {picard_note}"
                )
        else:
            try:
                from .planner_picard import run_picard_outer_loop

                qp_kwargs = {
                    "qp_solver": planner_auth.qp_solver,
                    "qp_rel_tol": planner_auth.qp_rel_tol,
                    "I_target": I_tgt,
                    "R": circuit_dynamics.R_ohm,
                    "L": circuit_dynamics.L_henry,
                    "dt": dt,
                    "I_lo": I_lo,
                    "I_hi": I_hi,
                    "V_lo": V_lo,
                    "V_hi": V_hi,
                    "weight_track_I": planner_auth.weight_track_I,
                    "weight_V": planner_auth.weight_V,
                    "weight_dI": planner_auth.weight_dI,
                    "weight_d2I": planner_auth.weight_d2I,
                    "max_iterations": planner_auth.max_qp_iterations,
                    "weight_isoflux": planner_auth.weight_isoflux,
                    "weight_xpoint_B": planner_auth.weight_xpoint_B,
                    "weight_psi_bry": planner_auth.weight_psi_bry if psi_bry_used else 0.0,
                }
                pic = run_picard_outer_loop(
                    machine_dir=Path(machine_dir),
                    inputs_dir=Path(inputs_dir),
                    circuit_order=order,
                    times=times,
                    I_plan=I_plan,
                    isoflux_pack=isoflux_pack,
                    qp_kwargs=qp_kwargs,
                    max_picard_iterations=int(planner_auth.max_picard_iterations),
                    picard_rel_tol=float(planner_auth.picard_rel_tol),
                    solve_qp_fn=solve_trajectory,
                )
                picard_status = str(pic.get("status") or "unknown")
                picard_note = str(pic.get("note") or "")
                picard_history = list(pic.get("history") or [])
                picard_used = bool(pic.get("picard"))
                picard_converged = bool(pic.get("converged"))
                picard_rel_tol_used = float(pic.get("picard_rel_tol", planner_auth.picard_rel_tol))
                if picard_used and pic.get("sol") is not None:
                    sol = pic["sol"]
                    I_plan = np.asarray(pic["I"], dtype=float)
                    isoflux_pack = pic.get("isoflux_pack") or isoflux_pack
                    picard_mode = pic.get("picard_mode")
                    if isoflux_pack is not None:
                        isoflux_pack["mode"] = isoflux_pack.get("mode") or (
                            "vacuum_coil_greens_plus_plasma_picard"
                        )
            except Exception as e:
                picard_status = "failed"
                picard_note = f"{type(e).__name__}: {e}"
                picard_used = False
                if planner_auth.require_picard:
                    raise PlannerError(
                        f"require_picard=true but Picard failed: {picard_note}"
                    ) from e
            if planner_auth.require_picard and not picard_used:
                raise PlannerError(
                    f"require_picard=true but status={picard_status!r}: {picard_note}"
                )
    V_plan = sol["V"]
    n_v_viol = int(sol["n_voltage_violations_raw"])
    # Cited fixed plant Vmax/Vmin remain hard fail-closed.
    # measured_peak_margin is a declared engineering envelope (1.2× peaks): I box is hard;
    # residual V overshoot is reported loudly but does not invent plant ratings.
    policy_src = (coil_limits.resolution or {}).get("policy")
    voltage_limit_ok = n_v_viol == 0
    if voltage_limit_ok:
        status = "ok"
    elif policy_src == "measured_peak_margin":
        status = "voltage_exceeds_measured_peak_margin"
        voltage_limit_ok = True  # soft for margin policy only
    else:
        status = "voltage_limit_violations"

    out_dir = Path(run_dir) / planner_auth.output_relpath
    out_dir.mkdir(parents=True, exist_ok=True)

    # Honesty: which voltage channels are measured vs ohmic-synthetic
    vmap_candidates = (
        Path(inputs_dir) / "voltage_map" / "voltage_map.resolved.json",
        Path(run_dir) / "contracts" / "voltage_map.resolved.json",
        Path(run_dir) / "06_authorities" / "contracts" / "voltage_map.resolved.json",
    )
    drive_labels: Dict[str, str] = {c: "unknown" for c in order}
    ohmic_sign_scale: Dict[str, Tuple[float, float]] = {c: (1.0, 1.0) for c in order}
    for vmap_path in vmap_candidates:
        if not vmap_path.exists():
            continue
        vmap = json.loads(vmap_path.read_text(encoding="utf-8"))
        circuits = vmap.get("circuits") or {}
        for c in order:
            spec = circuits.get(c) or {}
            comb = str(spec.get("combine", ""))
            try:
                sgn = float(spec.get("sign", 1.0))
            except (TypeError, ValueError):
                sgn = 1.0
            try:
                scl = float(spec.get("scale", 1.0))
            except (TypeError, ValueError):
                scl = 1.0
            ohmic_sign_scale[c] = (sgn, scl)
            if comb == "from_current_ohmic":
                drive_labels[c] = "ohmic_synthetic_IxR"
            elif comb in ("identity", "sum", "mean"):
                drive_labels[c] = "measured_fairmast_V"
            else:
                drive_labels[c] = comb or "unknown"
        break

    I_df = pd.DataFrame({"time": times, **{c: I_plan[:, i] for i, c in enumerate(order)}})
    V_df = pd.DataFrame({"time": times, **{c: V_plan[:, i] for i, c in enumerate(order)}})
    I_df.to_csv(out_dir / "planned_currents.csv", index=False)
    V_df.to_csv(out_dir / "planned_voltages.csv", index=False)

    # Model-gap: dynamics of measured I vs planned V vs FAIR-MAST / IxR refs
    V_dyn = voltages_from_dynamics(
        I_tgt,
        R=circuit_dynamics.R_ohm,
        L=circuit_dynamics.L_henry,
        dt=dt,
    )
    V_IxR = np.zeros_like(V_plan)
    R_vec = np.asarray(circuit_dynamics.R_ohm, dtype=float).reshape(-1)
    for i, c in enumerate(order):
        sgn, scl = ohmic_sign_scale[c]
        V_IxR[:, i] = float(sgn) * float(scl) * I_tgt[:, i] * float(R_vec[i])

    gap = build_voltage_model_gap(
        circuit_order=order,
        drive_labels=drive_labels,
        I_plan=I_plan,
        I_meas=I_tgt,
        V_plan=V_plan,
        V_obs=V_obs,
        V_dyn=V_dyn,
        V_IxR=V_IxR,
        R_ohm=R_vec,
    )
    gap_by_c = {str(r["circuit"]): r for r in gap.get("circuits") or []}

    resid_rows = []
    for i, c in enumerate(order):
        dlab = drive_labels[c]
        g = gap_by_c.get(c) or {}
        if dlab == "ohmic_synthetic_IxR":
            dV = V_plan[:, i] - V_IxR[:, i]
            v_ref_kind = "IxR_cited_dynamics_R"
            rms = g.get("rms_plan_minus_IxR_V")
            mae = None
            max_abs = None
            mask = np.isfinite(dV)
            if int(np.count_nonzero(mask)) >= 1:
                mae = float(np.mean(np.abs(dV[mask])))
                max_abs = float(np.max(np.abs(dV[mask])))
        else:
            dV = V_plan[:, i] - V_obs[:, i]
            v_ref_kind = "measured_fairmast_V"
            rms = g.get("rms_plan_minus_meas_V")
            mae = None
            max_abs = None
            mask = np.isfinite(dV)
            if int(np.count_nonzero(mask)) >= 1:
                mae = float(np.mean(np.abs(dV[mask])))
                max_abs = float(np.max(np.abs(dV[mask])))
                if rms is None:
                    rms = float(np.sqrt(np.mean(dV[mask] ** 2)))
        resid_rows.append(
            {
                "circuit": c,
                "drive_label": dlab,
                "residual_compare_class": residual_compare_class(dlab),
                "v_ref_kind": v_ref_kind,
                "rms_V": rms,
                "mae_V": mae,
                "max_abs_V": max_abs,
                "n": int(n_k),
                "i_track_rms_A": g.get("i_track_rms_A"),
                "rms_plan_minus_meas_V": g.get("rms_plan_minus_meas_V"),
                "rms_dyn_minus_meas_V": g.get("rms_dyn_minus_meas_V"),
                "rms_plan_minus_dyn_V": g.get("rms_plan_minus_dyn_V"),
                "rms_plan_minus_IxR_V": g.get("rms_plan_minus_IxR_V"),
                "corr_dyn_meas": g.get("corr_dyn_meas"),
                "corr_dyn_neg_meas": g.get("corr_dyn_neg_meas"),
                "gap_status": g.get("gap_status"),
            }
        )
    resid_df = pd.DataFrame(resid_rows)
    resid_df.to_csv(out_dir / "planning_residual_vs_measured_V.csv", index=False)
    (out_dir / "voltage_model_gap.json").write_text(
        json.dumps(gap, indent=2) + "\n", encoding="utf-8"
    )

    # Per-time residual timeseries (expert UI / CSV download)
    ts_rows: List[Dict[str, Any]] = []
    for k, t in enumerate(times):
        for i, c in enumerate(order):
            dlab = drive_labels[c]
            if dlab == "ohmic_synthetic_IxR":
                v_obs_k = float(V_IxR[k, i])
                dV_k = float(V_plan[k, i] - V_IxR[k, i])
                v_ref_kind = "IxR_cited_dynamics_R"
            else:
                v_obs_k = float(V_obs[k, i])
                dV_k = float(V_plan[k, i] - V_obs[k, i])
                v_ref_kind = "measured_fairmast_V"
            ts_rows.append(
                {
                    "time": float(t),
                    "circuit": c,
                    "drive_label": dlab,
                    "residual_compare_class": residual_compare_class(dlab),
                    "v_ref_kind": v_ref_kind,
                    "V_plan_V": float(V_plan[k, i]),
                    "V_obs_V": v_obs_k,
                    "V_dyn_Imeas_V": float(V_dyn[k, i]),
                    "V_IxR_V": float(V_IxR[k, i]),
                    "dV_V": dV_k,
                    "I_plan_A": float(I_plan[k, i]),
                    "I_meas_A": float(I_tgt[k, i]),
                }
            )
    ts_df = pd.DataFrame(ts_rows)
    ts_df.to_csv(out_dir / "planning_residual_timeseries.csv", index=False)

    plots_written: List[str] = []
    try:
        from .planner_plots import write_planner_iv_plots

        plots_written.extend(
            write_planner_iv_plots(
                out_dir,
                times=times,
                circuit_order=order,
                I_plan=I_plan,
                I_meas=I_tgt,
                V_plan=V_plan,
                V_obs=V_obs,
                coil_limits=coil_limits,
                drive_labels=drive_labels,
            )
        )
        from .planner_plots import write_planner_iv_plotly

        plotly_name = write_planner_iv_plotly(
            out_dir,
            times=times,
            circuit_order=order,
            I_plan=I_plan,
            I_meas=I_tgt,
            V_plan=V_plan,
            V_obs=V_obs,
            coil_limits=coil_limits,
            drive_labels=drive_labels,
        )
        if plotly_name:
            plots_written.append(plotly_name)
    except Exception as e:
        plots_written.append(f"plot_skipped:{type(e).__name__}: {e}")

    # Inventory EFIT shape targets (Path B1 authority + legacy efit_compare artifacts)
    shape_targets_available: Dict[str, Any] = {"present": False, "paths": []}
    for rel in (
        "inputs/shape_targets_authority/shape_targets.json",
        "07_planner/shape_targets.json",
        "04_efit_compare/efit_shape_timeseries.csv",
        "04_efit_compare/shape_scorecard.json",
        "04_efit_compare/efit_lcfs.csv",
    ):
        if (Path(run_dir) / rel).is_file():
            shape_targets_available["paths"].append(rel)
            shape_targets_available["present"] = True
    st_path = Path(inputs_dir) / "shape_targets_authority" / "shape_targets.json"
    if st_path.is_file() and "inputs/shape_targets_authority/shape_targets.json" not in shape_targets_available["paths"]:
        shape_targets_available["paths"].append("inputs/shape_targets_authority/shape_targets.json")
        shape_targets_available["present"] = True
    st_payload = shape_targets
    if st_payload is None and st_path.is_file():
        try:
            st_payload = json.loads(st_path.read_text(encoding="utf-8"))
        except Exception:
            st_payload = None
    if isinstance(st_payload, dict) and st_payload.get("present"):
        shape_targets_available["present"] = True
        shape_targets_available["status"] = st_payload.get("status")
        shape_targets_available["n_knots"] = st_payload.get("n_knots")
        shape_targets_available["found_scalars"] = st_payload.get("found_scalars")
        shape_targets_available["n_knots_with_lcfs_control_points"] = st_payload.get(
            "n_knots_with_lcfs_control_points"
        )
    shape_targets_available["note"] = (
        "Path B1–B3: EFIT++ archive shape targets feed vacuum-coil Green's isoflux; "
        "Picard freezes plasma offsets from FreeGSNKE forward GS when enabled."
    )

    isoflux_mode = None
    if isoflux_used:
        isoflux_mode = (
            "vacuum_coil_greens_plus_plasma_picard"
            if picard_used
            else "vacuum_coil_greens"
        )
        if isinstance(isoflux_pack, dict) and isoflux_pack.get("mode"):
            isoflux_mode = str(isoflux_pack["mode"])

    isoflux_residuals: Dict[str, Any] = {
        "used": isoflux_used,
        "status": isoflux_status,
        "mode": isoflux_mode,
        "note": isoflux_note,
    }
    if isoflux_used and isoflux_pack is not None:
        from .planner_isoflux import (
            evaluate_sensor_residuals,
            sensors_to_jsonable,
        )

        isoflux_residuals["sensors"] = sensors_to_jsonable(isoflux_pack)
        isoflux_residuals["planned"] = evaluate_sensor_residuals(I_plan, isoflux_pack)
        isoflux_residuals["measured_I_baseline"] = evaluate_sensor_residuals(
            I_tgt, isoflux_pack
        )
        (out_dir / "isoflux_residual.json").write_text(
            json.dumps(isoflux_residuals, indent=2) + "\n", encoding="utf-8"
        )

    picard_report: Dict[str, Any] = {
        "used": picard_used,
        "status": picard_status,
        "mode": picard_mode,
        "note": picard_note,
        "converged": bool(picard_converged) if picard_used else False,
        "picard_rel_tol": float(picard_rel_tol_used),
        "n_outers": (
            int(picard_history[-1]["outer"]) + 1
            if picard_used and picard_history
            else 0
        ),
        "n_outers_max": int(planner_auth.max_picard_iterations) if picard_used else 0,
        "history": picard_history,
    }
    (out_dir / "picard.json").write_text(
        json.dumps(picard_report, indent=2) + "\n", encoding="utf-8"
    )

    # Mutual inductance honesty: prefer structured fill_notes / exact tokens
    mutuals_note = mutuals_honesty_label(
        source=str(circuit_dynamics.source or ""),
        notes=str(circuit_dynamics.notes or ""),
        fill_notes=circuit_dynamics.fill_notes,
    )

    measured_rms = [
        r["rms_V"]
        for r in resid_rows
        if r["residual_compare_class"] == "measured_V"
        and r["rms_V"] is not None
        and np.isfinite(r["rms_V"])
    ]
    mean_rms_measured = float(np.mean(measured_rms)) if measured_rms else None
    deferred_rms = [
        r["rms_V"]
        for r in resid_rows
        if r["residual_compare_class"] == "deferred_ohmic_synthetic"
        and r["rms_V"] is not None
        and np.isfinite(r["rms_V"])
    ]
    mean_rms_deferred_ohmic = float(np.mean(deferred_rms)) if deferred_rms else None
    finite_all = [
        r["rms_V"]
        for r in resid_rows
        if r["rms_V"] is not None and np.isfinite(r["rms_V"])
    ]
    mean_rms = float(np.mean(finite_all)) if finite_all else None
    mean_i_track = gap.get("mean_i_track_rms_A")
    mean_plan_dyn = []
    for r in resid_rows:
        if r["residual_compare_class"] == "measured_V" and r.get("rms_plan_minus_dyn_V") is not None:
            try:
                v = float(r["rms_plan_minus_dyn_V"])
            except (TypeError, ValueError):
                continue
            if np.isfinite(v):
                mean_plan_dyn.append(v)
    mean_rms_plan_minus_dyn = float(np.mean(mean_plan_dyn)) if mean_plan_dyn else None

    meta = {
        "shot": shot,
        "status": status,
        # Path B0–B3 honesty labels
        "method": "gspulse_python",
        "method_version": "v1.5",
        "qp_solver": sol.get("qp_solver") or planner_auth.qp_solver,
        "require_isoflux": bool(planner_auth.require_isoflux),
        "require_picard": bool(planner_auth.require_picard),
        "require_psi_bry": bool(planner_auth.require_psi_bry),
        "picard": bool(picard_used),
        "picard_mode": picard_mode if picard_used else None,
        "picard_status": picard_status,
        "isoflux_cost": bool(isoflux_used),
        "isoflux_mode": isoflux_mode,
        "isoflux_status": isoflux_status,
        "psi_bry_cost": bool(psi_bry_used),
        "psi_bry_mode": psi_bry_mode if psi_bry_used else None,
        "psi_bry_status": psi_bry_status,
        "gspulse_reference": "https://arxiv.org/abs/2506.21760",
        "authority_version": planner_auth.authority_version,
        "t_start": float(t_start),
        "t_end": float(t_end),
        "n_knots": n_k,
        "dt_s": dt,
        "circuit_order": order,
        "drive_labels": drive_labels,
        "circuit_dynamics_source": circuit_dynamics.source,
        "circuit_dynamics_mutuals": mutuals_note,
        "coil_limits_citation": coil_limits.citation,
        "cost_history": sol["cost_history"],
        "n_voltage_violations_raw": n_v_viol,
        "residual_rms_by_circuit": {r["circuit"]: r["rms_V"] for r in resid_rows},
        "residual_rms_mean_V": mean_rms,
        "residual_rms_mean_measured_V": mean_rms_measured,
        "residual_rms_mean_deferred_ohmic_V": mean_rms_deferred_ohmic,
        "mean_i_track_rms_A": mean_i_track,
        "mean_rms_plan_minus_dyn_V": mean_rms_plan_minus_dyn,
        "voltage_model_gap": gap,
        "voltage_model_gap_overall": gap.get("overall_status"),
        "voltage_plan_model": "circuit_dynamics_RI_plus_L_dIdt",
        "voltage_residual_honesty": (
            "Planned V = R I + L dI/dt from cited R/L (and FreeGSNKE mutuals when retained). "
            "QP objective is I-tracking (weight_V ≪ weight_track_I); large ΔV with good I is expected. "
            "Prefer mean_i_track_rms_A and rms_plan_minus_dyn vs raw ΔV: when plan≈dyn(I_meas) "
            "the gap is active-only model vs terminal V (or polarity_suspect). "
            "deferred_ohmic_synthetic circuits score vs I×R_cited (not NaN / not FAIR-MAST V); "
            "evolutive ohmic fill may still use FreeGSNKE coil_resist (dual-R honesty)."
        ),
        "plots_written": plots_written,
        "shape_targets_available": shape_targets_available,
        "isoflux_residuals": {
            "used": isoflux_used,
            "status": isoflux_status,
            "mode": isoflux_mode,
            "planned": isoflux_residuals.get("planned"),
            "measured_I_baseline": isoflux_residuals.get("measured_I_baseline"),
            "note": isoflux_note,
        },
        "picard_report": {
            "used": picard_used,
            "status": picard_status,
            "mode": picard_mode,
            "note": picard_note,
            "converged": picard_report["converged"],
            "picard_rel_tol": picard_report["picard_rel_tol"],
            "n_outers": picard_report["n_outers"],
            "n_outers_max": picard_report["n_outers_max"],
        },
        "plasma_scalars": {
            "inventory": plasma_inventory,
            "psi_bry": {
                "used": psi_bry_used,
                "status": psi_bry_status,
                "mode": psi_bry_mode,
                "note": psi_bry_note,
                "psi_convention": (psi_bry_payload or {}).get("psi_convention"),
                "var_used": (psi_bry_payload or {}).get("var_used"),
                "attempts": (psi_bry_payload or {}).get("attempts"),
                "ejima_status": (
                    (psi_bry_payload or {}).get("ejima_status")
                    or (plasma_inventory or {}).get("ejima_status")
                ),
            },
        },
        "limitations": [
            "method=gspulse_python v1.5: current-tracking + circuit dynamics QP "
            f"(solver={planner_auth.qp_solver}) "
            "+ vacuum-coil Green's isoflux (require={planner_auth.require_isoflux}) "
            "+ Picard plasma freeze (require={planner_auth.require_picard}) "
            "+ optional ψ_bry absolute mean-flux (not upstream GSPulse MATLAB/MEQ)",
            (
                "picard=true mode=forward_gs_freeze_plasma_offsets — plasma offsets frozen "
                "from FreeGSNKE forward GS; linearized vacuum G still used in QP"
                if picard_used
                else f"picard=false status={picard_status} — {picard_note}"
            ),
            (
                f"isoflux_cost=true mode={isoflux_mode}"
                if isoflux_used
                else f"isoflux_cost=false status={isoflux_status} — {isoflux_note}"
            ),
            (
                f"psi_bry_cost=true mode={psi_bry_mode}"
                if psi_bry_used
                else f"psi_bry_cost=false status={psi_bry_status} — {psi_bry_note}"
            ),
            "Passives excluded while passive_resistivity awaiting_authority",
            "P3/P6 deferred_ohmic_synthetic scored vs I×R_cited (not measured-V fits); dual-R vs FreeGSNKE coil_resist possible",
            "Planned V is circuit-dynamics RI+L dI/dt; weight_V≪weight_I so large ΔV≠failed I-plan",
            "voltage_model_gap: polarity_suspect is YELLOW diagnostic only — never auto-flip voltage_map without citation",
            "Never invents coil I/V limits — citation required",
            "Voltage box limits are fail-closed: over-limit plans raise PlannerError",
            "Ejima ψ_bry requires cited R_p + L_I (never invent / never silent li→L_I)",
            f"circuit_dynamics_mutuals={mutuals_note}",
        ],
        "notes": planner_auth.notes,
    }
    (out_dir / "PLANNER.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    md = [
        f"# Planner report (shot {shot})",
        "",
        "ADR-004 Phase 2 — Python GSPulse-style feedforward planner (no MATLAB).",
        "",
        "**Voltage honesty:** planned V = `R I + L dI/dt` (circuit dynamics). "
        "The QP tracks currents (`weight_track_I`); `weight_V` is tiny — large ΔV with good I is expected "
        "while passives ρ await (ADR-005) and R/L are cited tables. "
        "Prefer **I-track RMS** and **plan−dyn** over raw ΔV: when `V_plan≈V_dyn(I_meas)` the gap is "
        "active-only model vs terminal V (or `polarity_suspect`). "
        "Circuits tagged `deferred_ohmic_synthetic` score vs **I×R_cited** (not FAIR-MAST V; dual-R vs FreeGSNKE possible).",
        "",
        f"- status: **{status}**",
        f"- voltage_model_gap: **{gap.get('overall_status')}** "
        f"(polarity_suspect={gap.get('n_polarity_suspect')}, "
        f"model_gap_expected={gap.get('n_model_gap_expected')})",
        f"- mean I-track RMS: {mean_i_track} A",
        f"- mean rms(plan−dyn) measured channels: {mean_rms_plan_minus_dyn} V",
        f"- method: `gspulse_python` v1.5 (solver={planner_auth.qp_solver}, "
        f"picard={bool(picard_used)}, "
        f"isoflux_cost={bool(isoflux_used)}, psi_bry={bool(psi_bry_used)}, "
        f"mode={meta.get('isoflux_mode')})",
        f"- picard: used={picard_used} status={picard_status} mode={picard_mode}",
        f"- psi_bry: used={psi_bry_used} status={psi_bry_status} mode={psi_bry_mode}",
        f"- knots: {n_k}  dt={dt:.6g}s  window=[{t_start:.6g},{t_end:.6g}]",
        f"- dynamics: `{circuit_dynamics.source}`",
        f"- mutuals: `{mutuals_note}`",
        f"- limits citation: {coil_limits.citation}",
        f"- voltage-limit violations (raw dynamics V): {n_v_viol}",
        f"- mean residual RMS (all circuits): {mean_rms}",
        f"- mean residual RMS (measured V only): {mean_rms_measured}",
        f"- mean residual RMS (deferred ohmic only): {mean_rms_deferred_ohmic}",
        f"- isoflux status: {isoflux_status} — {isoflux_note}",
        "",
        "## Planning residual vs voltages (RMS)",
        "",
    ]
    for r in resid_rows:
        md.append(
            f"- **{r['circuit']}** ({r['drive_label']} / {r['residual_compare_class']} / "
            f"{r.get('gap_status')}): rms={r['rms_V']} V "
            f"(I_rms={r.get('i_track_rms_A')} A; "
            f"plan−dyn={r.get('rms_plan_minus_dyn_V')} V; "
            f"corr_dyn_meas={r.get('corr_dyn_meas')})"
        )
    md.append("")
    md.append("## Artifacts")
    md.append("- `planned_currents.csv` / `planned_voltages.csv`")
    md.append("- `planning_residual_vs_measured_V.csv` (per-circuit summary + gap fields)")
    md.append("- `planning_residual_timeseries.csv` (per-time ΔV + V_dyn + IxR)")
    md.append("- `voltage_model_gap.json` (I-track / model-gap / polarity diagnostic)")
    if isoflux_used:
        md.append("- `isoflux_residual.json` (vacuum-coil Green's sensor residuals)")
    md.append("- `picard.json` (Path B3 outer-loop status)")
    md.append("- `plasma_scalars.json` (Path B4 Ip/profile/ψ_bry inventory)")
    if plots_written:
        md.append(f"- plots: {', '.join(plots_written)}")
    md.append("")
    md.append("## Shape targets (Path B1)")
    md.append(f"- present={shape_targets_available['present']}: {shape_targets_available.get('paths')}")
    if shape_targets_available.get("found_scalars") is not None:
        md.append(f"- found_scalars: {shape_targets_available.get('found_scalars')}")
    md.append(f"- {shape_targets_available['note']}")
    md.append("")
    md.append("## Isoflux (Path B2)")
    md.append(f"- used={isoflux_used} status={isoflux_status} mode={meta.get('isoflux_mode')}")
    planned_iso = (isoflux_residuals.get("planned") or {}) if isoflux_used else {}
    if planned_iso:
        md.append(
            f"- planned isoflux_rms_mean={planned_iso.get('isoflux_rms_mean')} "
            f"xpoint_B_rms_mean={planned_iso.get('xpoint_B_rms_mean')}"
        )
    md.append(f"- {isoflux_note}")
    md.append("")
    md.append("## Picard (Path B3)")
    md.append(f"- used={picard_used} status={picard_status} mode={picard_mode}")
    md.append(f"- {picard_note}")
    md.append("")
    md.append("## Plasma scalars / ψ_bry (Path B4)")
    md.append(f"- inventory: {plasma_inventory}")
    md.append(f"- used={psi_bry_used} status={psi_bry_status} mode={psi_bry_mode}")
    md.append(f"- {psi_bry_note}")
    md.append("")
    md.append("## Limitations")
    for lim in meta["limitations"]:
        md.append(f"- {lim}")
    (out_dir / "PLANNER.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    if not voltage_limit_ok:
        raise PlannerError(
            f"planner voltage box constraints violated at {n_v_viol} knot×circuit samples "
            f"(cited coil_limits); see {out_dir / 'PLANNER.json'} — never relax limits silently"
        )
    if status == "voltage_exceeds_measured_peak_margin":
        meta["limitations"].append(
            f"Planned V exceeds measured_peak_margin envelope at {n_v_viol} samples — "
            "increase margin_factor or accept as soft engineering headroom (not a plant rating)"
        )
        (out_dir / "PLANNER.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "status": status,
        "path": str(out_dir),
        "n_knots": n_k,
        "residual_rms_by_circuit": meta["residual_rms_by_circuit"],
        "residual_rms_mean_V": mean_rms,
        "residual_rms_mean_measured_V": mean_rms_measured,
        "residual_rms_mean_deferred_ohmic_V": mean_rms_deferred_ohmic,
        "mean_i_track_rms_A": mean_i_track,
        "mean_rms_plan_minus_dyn_V": mean_rms_plan_minus_dyn,
        "voltage_model_gap_overall": gap.get("overall_status"),
        "n_voltage_violations_raw": n_v_viol,
        "meta": meta,
    }
