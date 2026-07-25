"""Path B4: plasma scalars + ψ_bry target for GSPulse-style absolute mean-flux cost.

Modes (authority-declared priority — never invent Rp / L_I / ψ0):
  1. archive_psi_bry — EFIT++ archive boundary flux scalars
  2. archive_vloop_integrate — ψ(t)=ψ0−∫Vloop dt (ψ0 from archive)
  3. ejima_cited_Rp_LI — Ejima eq. only when R_p and L_I are cited in authority

Attaches a mean absolute-flux sensor (GSPulse ``Flux absolute average`` vocabulary)
onto the existing vacuum-coil Green's pack when LCFS geometry exists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .planner import PlannerError
from .planner_isoflux import IsofluxSensors


class PlasmaScalarsError(ValueError):
    pass


def _strict_bool(value: Any, name: str, *, default: Optional[bool] = None) -> bool:
    if value is None and default is not None:
        return default
    if not isinstance(value, bool):
        raise PlasmaScalarsError(f"{name} must be a JSON boolean (got {type(value).__name__})")
    return value


ALLOWED_MODES = (
    "archive_psi_bry",
    "archive_vloop_integrate",
    "ejima_cited_Rp_LI",
)


@dataclass(frozen=True)
class EjimaAuthority:
    status: str = "awaiting_authority"  # awaiting_authority | cited
    citation: Optional[str] = None
    R_p_ohm: Optional[float] = None
    L_I_henry: Optional[float] = None
    notes: str = ""

    def validate(self) -> None:
        if self.status not in {"awaiting_authority", "cited"}:
            raise PlasmaScalarsError("ejima.status must be awaiting_authority or cited")
        if self.status == "cited":
            if not (self.citation and str(self.citation).strip()):
                raise PlasmaScalarsError("ejima.citation required when status=cited")
            if self.R_p_ohm is None or float(self.R_p_ohm) < 0:
                raise PlasmaScalarsError("ejima.R_p_ohm must be >= 0 when cited")
            if self.L_I_henry is None or float(self.L_I_henry) <= 0:
                raise PlasmaScalarsError("ejima.L_I_henry must be > 0 when cited")


@dataclass(frozen=True)
class PlasmaScalarsAuthority:
    authority_name: str = "plasma_scalars"
    authority_version: str = "1.0.0"
    enabled: bool = True
    require: bool = False
    source: str = "fairmast_level2_equilibrium"
    equilibrium_group: str = "equilibrium"
    psi_convention: str = "Wb_per_radian_honest_label"
    mode_priority: Tuple[str, ...] = ALLOWED_MODES
    psi_bry_vars: Tuple[str, ...] = ("psi_boundary", "psi_bry", "psibry", "psi_bound")
    vloop_vars: Tuple[str, ...] = ("vloop_dynamic", "vloop", "loop_voltage", "Vloop")
    ip_source: str = "inputs/ip.csv"
    profile_trajectory_relpath: str = (
        "inputs/profile_trajectory_authority/profile_trajectory.json"
    )
    ejima: EjimaAuthority = field(default_factory=EjimaAuthority)
    notes: str = ""

    def validate(self) -> None:
        if not self.authority_name.strip():
            raise PlasmaScalarsError("authority_name required")
        if self.source != "fairmast_level2_equilibrium":
            raise PlasmaScalarsError("source must be fairmast_level2_equilibrium")
        if not self.mode_priority:
            raise PlasmaScalarsError("mode_priority required")
        for m in self.mode_priority:
            if m not in ALLOWED_MODES:
                raise PlasmaScalarsError(f"unsupported mode {m!r}")
        self.ejima.validate()

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "authority_name": self.authority_name,
            "authority_version": self.authority_version,
            "enabled": self.enabled,
            "require": self.require,
            "source": self.source,
            "equilibrium_group": self.equilibrium_group,
            "psi_convention": self.psi_convention,
            "mode_priority": list(self.mode_priority),
            "psi_bry_vars": list(self.psi_bry_vars),
            "vloop_vars": list(self.vloop_vars),
            "ip_source": self.ip_source,
            "profile_trajectory_relpath": self.profile_trajectory_relpath,
            "ejima": {
                "status": self.ejima.status,
                "citation": self.ejima.citation,
                "R_p_ohm": self.ejima.R_p_ohm,
                "L_I_henry": self.ejima.L_I_henry,
                "notes": self.ejima.notes,
            },
            "notes": self.notes,
        }


def load_plasma_scalars_authority(path: Path) -> PlasmaScalarsAuthority:
    path = Path(path)
    if not path.exists():
        raise PlasmaScalarsError(f"plasma_scalars_authority not found: {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise PlasmaScalarsError("plasma_scalars_authority must be a JSON object")
    ej = obj.get("ejima") if isinstance(obj.get("ejima"), dict) else {}
    auth = PlasmaScalarsAuthority(
        authority_name=str(obj.get("authority_name", "plasma_scalars")),
        authority_version=str(obj.get("authority_version", "1.0.0")),
        enabled=_strict_bool(obj.get("enabled"), "enabled", default=True),
        require=_strict_bool(obj.get("require"), "require", default=False),
        source=str(obj.get("source", "fairmast_level2_equilibrium")),
        equilibrium_group=str(obj.get("equilibrium_group", "equilibrium")),
        psi_convention=str(obj.get("psi_convention", "Wb_per_radian_honest_label")),
        mode_priority=tuple(str(x) for x in (obj.get("mode_priority") or ALLOWED_MODES)),
        psi_bry_vars=tuple(
            str(x)
            for x in (
                obj.get("psi_bry_vars")
                or ("psi_boundary", "psi_bry", "psibry", "psi_bound")
            )
        ),
        vloop_vars=tuple(
            str(x)
            for x in (
                obj.get("vloop_vars")
                or ("vloop_dynamic", "vloop", "loop_voltage", "Vloop")
            )
        ),
        ip_source=str(obj.get("ip_source", "inputs/ip.csv")),
        profile_trajectory_relpath=str(
            obj.get(
                "profile_trajectory_relpath",
                "inputs/profile_trajectory_authority/profile_trajectory.json",
            )
        ),
        ejima=EjimaAuthority(
            status=str(ej.get("status", "awaiting_authority")),
            citation=ej.get("citation"),
            R_p_ohm=(float(ej["R_p_ohm"]) if ej.get("R_p_ohm") is not None else None),
            L_I_henry=(
                float(ej["L_I_henry"]) if ej.get("L_I_henry") is not None else None
            ),
            notes=str(ej.get("notes", "")),
        ),
        notes=str(obj.get("notes", "")),
    )
    auth.validate()
    return auth


def write_plasma_scalars_authority(inputs_dir: Path, auth: PlasmaScalarsAuthority) -> Path:
    inputs_dir = Path(inputs_dir)
    root = inputs_dir / "plasma_scalars_authority"
    root.mkdir(parents=True, exist_ok=True)
    auth.validate()
    path = root / "plasma_scalars_authority.json"
    path.write_text(json.dumps(auth.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def _first_present_series(
    series_map: Dict[str, Optional[np.ndarray]], names: Sequence[str]
) -> Tuple[Optional[str], Optional[np.ndarray]]:
    for n in names:
        s = series_map.get(n)
        if s is not None and np.isfinite(s).any():
            return n, s
    return None, None


def _interp_series(
    times_q: np.ndarray, t_src: np.ndarray, y_src: np.ndarray
) -> np.ndarray:
    return np.interp(times_q, t_src, y_src)


def integrate_vloop_to_psi(
    *,
    times: np.ndarray,
    vloop_V: np.ndarray,
    psi0: float,
) -> np.ndarray:
    """ψ(t)=ψ0 − ∫ Vloop dt  (Vp = −dψ/dt ⇒ dψ = −Vloop dt)."""
    t = np.asarray(times, dtype=float).ravel()
    v = np.asarray(vloop_V, dtype=float).ravel()
    if t.size != v.size or t.size < 1:
        raise PlasmaScalarsError("vloop integrate: times/vloop length mismatch")
    psi = np.zeros_like(t)
    psi[0] = float(psi0)
    for k in range(t.size - 1):
        dt = float(t[k + 1] - t[k])
        if dt <= 0:
            raise PlasmaScalarsError("vloop integrate: times must be strictly increasing")
        psi[k + 1] = psi[k] - 0.5 * (v[k] + v[k + 1]) * dt
    return psi


def integrate_ejima_to_psi(
    *,
    times: np.ndarray,
    Ip_A: np.ndarray,
    R_p_ohm: float,
    L_I_henry: float,
    psi0: float,
) -> np.ndarray:
    """Discrete Ejima with constant L_I: Vp = Rp Ip + L_I dIp/dt; ψ˙ = −Vp."""
    t = np.asarray(times, dtype=float).ravel()
    Ip = np.asarray(Ip_A, dtype=float).ravel()
    if t.size != Ip.size or t.size < 2:
        raise PlasmaScalarsError("ejima integrate needs >=2 samples")
    if float(R_p_ohm) < 0 or float(L_I_henry) <= 0:
        raise PlasmaScalarsError("ejima requires R_p>=0 and L_I>0")
    psi = np.zeros_like(t)
    psi[0] = float(psi0)
    for k in range(t.size - 1):
        dt = float(t[k + 1] - t[k])
        if dt <= 0:
            raise PlasmaScalarsError("ejima: times must be strictly increasing")
        dIp_dt = (Ip[k + 1] - Ip[k]) / dt
        Ip_mid = 0.5 * (Ip[k] + Ip[k + 1])
        Vp = float(R_p_ohm) * Ip_mid + float(L_I_henry) * dIp_dt
        psi[k + 1] = psi[k] - Vp * dt
    return psi


def inventory_plasma_drive(
    *,
    inputs_dir: Path,
    times: np.ndarray,
    auth: PlasmaScalarsAuthority,
) -> Dict[str, Any]:
    """Honest inventory of Ip + profile_trajectory (no invent)."""
    from .profile_trajectory import try_load_built_trajectory

    inputs_dir = Path(inputs_dir)
    inv: Dict[str, Any] = {
        "ip_present": False,
        "ip_path": None,
        "profile_trajectory_present": False,
        "profile_trajectory_status": None,
        "profile_fit_mode_used": None,
        "n_profile_knots": None,
        "n_planner_knots": int(np.asarray(times).size),
        "authority_version": auth.authority_version,
    }
    ip_path = inputs_dir / "ip.csv"
    if ip_path.is_file():
        inv["ip_present"] = True
        inv["ip_path"] = "inputs/ip.csv"
    traj = try_load_built_trajectory(inputs_dir)
    if traj is not None:
        inv["profile_trajectory_present"] = True
        inv["profile_trajectory_status"] = traj.status
        inv["profile_fit_mode_used"] = traj.fit_mode_used
        inv["n_profile_knots"] = len(traj.knots)
    else:
        pt = inputs_dir / "profile_trajectory_authority" / "profile_trajectory.json"
        if pt.is_file():
            try:
                obj = json.loads(pt.read_text(encoding="utf-8"))
                inv["profile_trajectory_present"] = True
                inv["profile_trajectory_status"] = obj.get("status")
                inv["profile_fit_mode_used"] = obj.get("fit_mode_used")
            except Exception:
                pass
    return inv


def build_psi_bry_targets(
    *,
    times: np.ndarray,
    auth: PlasmaScalarsAuthority,
    shape_targets: Optional[Dict[str, Any]] = None,
    cache_dir: Optional[Path] = None,
    inputs_dir: Optional[Path] = None,
    Ip_A: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Resolve ψ_bry(t) by mode_priority. Soft-skips when data/citation missing."""
    auth.validate()
    times = np.asarray(times, dtype=float).ravel()
    out: Dict[str, Any] = {
        "ok": False,
        "mode": None,
        "status": "skipped",
        "psi_bry_Wb": None,
        "psi_convention": auth.psi_convention,
        "var_used": None,
        "note": "",
        "attempts": [],
    }
    if not auth.enabled:
        out["status"] = "disabled"
        out["note"] = "plasma_scalars_authority.enabled=false"
        return out

    series_map: Dict[str, Optional[np.ndarray]] = {}
    t_src: Optional[np.ndarray] = None
    if isinstance(shape_targets, dict) and shape_targets.get("knots"):
        knots = shape_targets["knots"]
        t_src = np.asarray(
            [float(k.get("t_s")) for k in knots if isinstance(k, dict)], dtype=float
        )
        for name in list(auth.psi_bry_vars) + list(auth.vloop_vars) + ["wmhd", "li"]:
            vals = []
            for k in knots:
                if not isinstance(k, dict):
                    continue
                sc = k.get("scalars") if isinstance(k.get("scalars"), dict) else {}
                raw = sc.get(name)
                try:
                    vals.append(float(raw) if raw is not None else np.nan)
                except (TypeError, ValueError):
                    vals.append(np.nan)
            arr = np.asarray(vals, dtype=float)
            series_map[name] = arr if np.isfinite(arr).any() else None

    if cache_dir is not None:
        try:
            from .efit_compare import _open_equilibrium, _series_1d, _time_coord

            ds = _open_equilibrium(Path(cache_dir), auth.equilibrium_group)
            t_eq = _time_coord(ds)
            for name in list(auth.psi_bry_vars) + list(auth.vloop_vars) + ["wmhd", "li"]:
                if series_map.get(name) is not None:
                    continue
                s = _series_1d(ds, name)
                if s is not None and np.isfinite(s).any():
                    series_map[name] = s
                    t_src = t_eq
        except Exception as e:
            out["attempts"].append(
                {"source": "equilibrium_archive", "error": f"{type(e).__name__}: {e}"}
            )

    for mode in auth.mode_priority:
        if mode == "archive_psi_bry":
            var, s = _first_present_series(series_map, auth.psi_bry_vars)
            if var is None or s is None or t_src is None:
                out["attempts"].append({"mode": mode, "status": "missing_archive_psi_bry"})
                continue
            psi = _interp_series(times, t_src, s)
            if not np.isfinite(psi).all():
                out["attempts"].append({"mode": mode, "status": "nonfinite_after_interp"})
                continue
            out.update(
                {
                    "ok": True,
                    "mode": mode,
                    "status": "ok",
                    "psi_bry_Wb": [float(x) for x in psi],
                    "var_used": var,
                    "note": (
                        f"archive ψ_bry from equilibrium/{var}; "
                        f"convention={auth.psi_convention}"
                    ),
                }
            )
            return out

        if mode == "archive_vloop_integrate":
            var, s = _first_present_series(series_map, auth.vloop_vars)
            if var is None or s is None or t_src is None:
                out["attempts"].append({"mode": mode, "status": "missing_archive_vloop"})
                continue
            vloop = _interp_series(times, t_src, s)
            psi0 = None
            pvar, ps = _first_present_series(series_map, auth.psi_bry_vars)
            if pvar is not None and ps is not None:
                psi0 = float(np.interp(float(times[0]), t_src, ps))
            if psi0 is None or not np.isfinite(psi0):
                out["attempts"].append(
                    {
                        "mode": mode,
                        "status": "missing_psi0_for_vloop_integrate",
                        "note": "refuse to invent ψ0; need archive psi_bry at t0",
                    }
                )
                continue
            psi = integrate_vloop_to_psi(times=times, vloop_V=vloop, psi0=psi0)
            out.update(
                {
                    "ok": True,
                    "mode": mode,
                    "status": "ok",
                    "psi_bry_Wb": [float(x) for x in psi],
                    "var_used": var,
                    "psi0_var": pvar,
                    "psi0": psi0,
                    "note": (
                        f"ψ(t)=ψ0−∫{var} dt with ψ0 from {pvar}; "
                        f"convention={auth.psi_convention}"
                    ),
                }
            )
            return out

        if mode == "ejima_cited_Rp_LI":
            if auth.ejima.status != "cited":
                out["attempts"].append(
                    {
                        "mode": mode,
                        "status": "ejima_awaiting_authority",
                        "note": auth.ejima.notes,
                    }
                )
                continue
            if Ip_A is None:
                if inputs_dir is None:
                    out["attempts"].append({"mode": mode, "status": "missing_Ip"})
                    continue
                try:
                    from .planner_picard import load_ip_series, interp_ip

                    t_ip, ip_src = load_ip_series(Path(inputs_dir))
                    Ip_A = np.asarray(
                        [interp_ip(float(tt), t_ip, ip_src) for tt in times],
                        dtype=float,
                    )
                except Exception as e:
                    out["attempts"].append(
                        {"mode": mode, "status": "ip_load_failed", "error": str(e)}
                    )
                    continue
            Ip_A = np.asarray(Ip_A, dtype=float).ravel()
            if Ip_A.size != times.size:
                out["attempts"].append({"mode": mode, "status": "Ip_length_mismatch"})
                continue
            psi0 = None
            pvar, ps = _first_present_series(series_map, auth.psi_bry_vars)
            if pvar is not None and ps is not None and t_src is not None:
                psi0 = float(np.interp(float(times[0]), t_src, ps))
            if psi0 is None or not np.isfinite(psi0):
                out["attempts"].append(
                    {
                        "mode": mode,
                        "status": "missing_psi0_for_ejima",
                        "note": "refuse to invent ψ0",
                    }
                )
                continue
            try:
                psi = integrate_ejima_to_psi(
                    times=times,
                    Ip_A=Ip_A,
                    R_p_ohm=float(auth.ejima.R_p_ohm),
                    L_I_henry=float(auth.ejima.L_I_henry),
                    psi0=float(psi0),
                )
            except Exception as e:
                out["attempts"].append(
                    {"mode": mode, "status": "ejima_integrate_failed", "error": str(e)}
                )
                continue
            out.update(
                {
                    "ok": True,
                    "mode": mode,
                    "status": "ok",
                    "psi_bry_Wb": [float(x) for x in psi],
                    "var_used": "ejima",
                    "psi0_var": pvar,
                    "psi0": psi0,
                    "ejima_citation": auth.ejima.citation,
                    "R_p_ohm": float(auth.ejima.R_p_ohm),
                    "L_I_henry": float(auth.ejima.L_I_henry),
                    "note": (
                        f"Ejima ψ_bry with cited Rp={auth.ejima.R_p_ohm} Ω, "
                        f"L_I={auth.ejima.L_I_henry} H ({auth.ejima.citation}); "
                        f"ψ0 from {pvar}"
                    ),
                }
            )
            return out

    out["status"] = "skipped_no_mode"
    out["note"] = (
        "No ψ_bry mode succeeded (archive missing and/or Ejima awaiting citation). "
        "Never invents Rp/L_I/ψ0."
    )
    return out


def attach_psi_bry_sensors(
    pack: Dict[str, Any],
    *,
    psi_bry_Wb: Sequence[float],
) -> Dict[str, Any]:
    """Add mean absolute-flux sensors: mean(G_psi) @ I ≈ ψ_bry − mean(plasma)."""
    knots = list(pack.get("knots") or [])
    psi = np.asarray(psi_bry_Wb, dtype=float).ravel()
    n = min(len(knots), psi.size)
    n_attached = 0
    for k in range(n):
        entry = dict(knots[k])
        iso = entry.get("isoflux")
        if not isinstance(iso, IsofluxSensors) or iso.G_psi_full is None:
            entry["psi_bry"] = None
            knots[k] = entry
            continue
        G_full = np.asarray(iso.G_psi_full, dtype=float)
        G_mean = np.mean(G_full, axis=0, keepdims=True)
        desired = float(psi[k])
        sens = IsofluxSensors(
            G=G_mean,
            target=np.asarray([desired], dtype=float),
            labels=("psi_bry_mean",),
            kind="psi_bry_mean",
            r_m=np.asarray(iso.r_all_m if iso.r_all_m is not None else iso.r_m),
            z_m=np.asarray(iso.z_all_m if iso.z_all_m is not None else iso.z_m),
            note=(
                f"absolute mean flux target={desired}; desired_total_Wb={desired}; "
                "GSPulse flux_abs_avg"
            ),
            r_all_m=iso.r_all_m,
            z_all_m=iso.z_all_m,
            G_psi_full=G_full,
        )
        entry["psi_bry"] = sens
        knots[k] = entry
        n_attached += 1
    out = dict(pack)
    out["knots"] = knots
    out["psi_bry_sensors"] = n_attached
    out["ok"] = bool(pack.get("ok")) or n_attached > 0
    return out


def _parse_desired_total(note: str, fallback: float) -> float:
    marker = "desired_total_Wb="
    if marker in note:
        try:
            return float(note.split(marker, 1)[1].split(";", 1)[0].split()[0])
        except Exception:
            return fallback
    return fallback


def apply_plasma_offset_psi_bry(
    sens: IsofluxSensors,
    *,
    I_k: np.ndarray,
    psi_total: np.ndarray,
) -> IsofluxSensors:
    """Adjust target so mean(G)@I ≈ desired_total − mean(plasma)."""
    if sens.G_psi_full is None:
        raise PlannerError("psi_bry sensor missing G_psi_full")
    G_full = np.asarray(sens.G_psi_full, dtype=float)
    I_k = np.asarray(I_k, dtype=float).ravel()
    psi_vac = G_full @ I_k
    psi_p = np.asarray(psi_total, dtype=float).ravel() - psi_vac
    desired = _parse_desired_total(
        sens.note or "", float(np.asarray(sens.target).ravel()[0])
    )
    target = float(desired) - float(np.mean(psi_p))
    return replace(
        sens,
        target=np.asarray([target], dtype=float),
        note=(
            f"absolute mean flux target={target}; desired_total_Wb={desired}; "
            "GSPulse flux_abs_avg; plasma_picard_offset"
        ),
    )
