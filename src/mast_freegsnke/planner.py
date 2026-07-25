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
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .coil_limits import CoilLimitsAuthority, CoilLimitsError, load_coil_limits, write_coil_limits


class PlannerError(RuntimeError):
    pass


FIT_MODES = ()  # reserved


@dataclass(frozen=True)
class PlannerAuthority:
    authority_name: str = "planner"
    authority_version: str = "1.0.0"
    enabled: bool = False
    require: bool = False
    output_relpath: str = "07_planner"
    n_knots: int = 21
    knot_policy: str = "linspace_window_inclusive"
    weight_track_I: float = 1.0
    weight_V: float = 1.0e-6
    weight_dI: float = 1.0e-2
    weight_d2I: float = 1.0e-3
    max_qp_iterations: int = 40
    notes: str = ""

    def validate(self) -> None:
        if not self.authority_name.strip():
            raise PlannerError("authority_name required")
        if self.knot_policy != "linspace_window_inclusive":
            raise PlannerError("knot_policy must be linspace_window_inclusive (v1)")
        if not (2 <= int(self.n_knots) <= 500):
            raise PlannerError("n_knots must be in [2, 500]")
        for name in ("weight_track_I", "weight_V", "weight_dI", "weight_d2I"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or float(v) < 0:
                raise PlannerError(f"{name} must be >= 0")
        if not (1 <= int(self.max_qp_iterations) <= 500):
            raise PlannerError("max_qp_iterations must be in [1, 500]")
        if not isinstance(self.enabled, bool) or not isinstance(self.require, bool):
            raise PlannerError("enabled/require must be bool")
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
        authority_version=str(obj.get("authority_version", "1.0.0")),
        enabled=bool(obj.get("enabled", False)),
        require=bool(obj.get("require", False)),
        output_relpath=str(obj.get("output_relpath", "07_planner")),
        n_knots=int(obj.get("n_knots", 21)),
        knot_policy=str(obj.get("knot_policy", "linspace_window_inclusive")),
        weight_track_I=float(obj.get("weight_track_I", 1.0)),
        weight_V=float(obj.get("weight_V", 1.0e-6)),
        weight_dI=float(obj.get("weight_dI", 1.0e-2)),
        weight_d2I=float(obj.get("weight_d2I", 1.0e-3)),
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
        return {
            "circuit_order": list(self.circuit_order),
            "R_ohm": np.asarray(self.R_ohm, dtype=float).tolist(),
            "L_henry": np.asarray(self.L_henry, dtype=float).tolist(),
            "source": self.source,
            "notes": self.notes,
        }


def load_circuit_dynamics(path: Path) -> CircuitDynamics:
    path = Path(path)
    if not path.exists():
        raise PlannerError(f"circuit_dynamics snapshot not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    dyn = CircuitDynamics(
        circuit_order=[str(x) for x in obj["circuit_order"]],
        R_ohm=np.asarray(obj["R_ohm"], dtype=float),
        L_henry=np.asarray(obj["L_henry"], dtype=float),
        source=str(obj.get("source", "")),
        notes=str(obj.get("notes", "")),
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
    """Y shape (n_time, n_col) → interpolate each column at t_query."""
    out = np.zeros((len(t_query), Y.shape[1]), dtype=float)
    for j in range(Y.shape[1]):
        out[:, j] = np.interp(t_query, t_src, Y[:, j])
    return out


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
) -> Dict[str, Any]:
    """Projected trajectory optimizer (numpy-only GSPulse-inspired cost).

    Decision variable: I[t, circuit]. Voltages follow circuit dynamics.
    Iterates: unconstrained Tikhonov step on I toward target + smoothness,
    project I onto bounds, recompute V, shrink dI where V exceeds bounds.
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
            I_new[k] = acc / max(wsum, 1e-30)
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
            # Mild pull toward smaller |V| without inventing a new profile law
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
    V_clipped = np.clip(V, V_lo, V_hi)
    return {
        "I": I,
        "V": V,
        "V_clipped": V_clipped,
        "cost_history": hist_cost,
        "n_voltage_violations_raw": int(np.sum((V > V_hi) | (V < V_lo))),
        "n_voltage_clip_changes": int(np.sum(np.abs(V - V_clipped) > 1e-12)),
    }


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

    sol = solve_trajectory_qp(
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
    )
    I_plan = sol["I"]
    V_plan = sol["V"]

    out_dir = Path(run_dir) / planner_auth.output_relpath
    out_dir.mkdir(parents=True, exist_ok=True)

    # Honesty: which voltage channels are measured vs ohmic-synthetic
    vmap_candidates = (
        Path(inputs_dir) / "voltage_map" / "voltage_map.resolved.json",
        Path(run_dir) / "contracts" / "voltage_map.resolved.json",
        Path(run_dir) / "06_authorities" / "contracts" / "voltage_map.resolved.json",
    )
    drive_labels: Dict[str, str] = {c: "unknown" for c in order}
    for vmap_path in vmap_candidates:
        if not vmap_path.exists():
            continue
        vmap = json.loads(vmap_path.read_text(encoding="utf-8"))
        circuits = vmap.get("circuits") or {}
        for c in order:
            comb = str((circuits.get(c) or {}).get("combine", ""))
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

    resid_rows = []
    for i, c in enumerate(order):
        dV = V_plan[:, i] - V_obs[:, i]
        resid_rows.append(
            {
                "circuit": c,
                "drive_label": drive_labels[c],
                "rms_V": float(np.sqrt(np.mean(dV**2))),
                "mae_V": float(np.mean(np.abs(dV))),
                "max_abs_V": float(np.max(np.abs(dV))),
                "n": int(n_k),
            }
        )
    resid_df = pd.DataFrame(resid_rows)
    resid_df.to_csv(out_dir / "planning_residual_vs_measured_V.csv", index=False)

    meta = {
        "shot": shot,
        "status": "ok",
        "authority_version": planner_auth.authority_version,
        "t_start": float(t_start),
        "t_end": float(t_end),
        "n_knots": n_k,
        "dt_s": dt,
        "circuit_order": order,
        "drive_labels": drive_labels,
        "circuit_dynamics_source": circuit_dynamics.source,
        "coil_limits_citation": coil_limits.citation,
        "cost_history": sol["cost_history"],
        "n_voltage_violations_raw": sol["n_voltage_violations_raw"],
        "n_voltage_clip_changes": sol["n_voltage_clip_changes"],
        "residual_rms_by_circuit": {r["circuit"]: r["rms_V"] for r in resid_rows},
        "limitations": [
            "v1 planner: current-tracking + circuit dynamics QP (GSPulse cost vocabulary); "
            "full GS Picard isoflux terms not yet wired",
            "Passives excluded while passive_resistivity awaiting_authority",
            "P3/P6 measured voltages may be ohmic_synthetic_IxR — residuals labeled honestly",
            "Never invents coil I/V limits — citation required",
        ],
        "notes": planner_auth.notes,
    }
    (out_dir / "PLANNER.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    md = [
        f"# Planner report (shot {shot})",
        "",
        "ADR-004 Phase 2 — Python GSPulse-style feedforward planner (no MATLAB).",
        "",
        f"- knots: {n_k}  dt={dt:.6g}s  window=[{t_start:.6g},{t_end:.6g}]",
        f"- dynamics: `{circuit_dynamics.source}`",
        f"- limits citation: {coil_limits.citation}",
        "",
        "## Planning residual vs voltages (RMS)",
        "",
    ]
    for r in resid_rows:
        md.append(
            f"- **{r['circuit']}** ({r['drive_label']}): rms={r['rms_V']:.6g} V"
        )
    md.append("")
    md.append("## Limitations")
    for lim in meta["limitations"]:
        md.append(f"- {lim}")
    (out_dir / "PLANNER.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "status": "ok",
        "path": str(out_dir),
        "n_knots": n_k,
        "residual_rms_by_circuit": meta["residual_rms_by_circuit"],
        "meta": meta,
    }
