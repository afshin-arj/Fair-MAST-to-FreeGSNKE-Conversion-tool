"""UI/CLI helpers: save planner R/L + passive ρ edits and re-run planner only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


class PlannerReplanError(ValueError):
    pass


def load_editable_circuit_table(repo_root: Path) -> Dict[str, Any]:
    """Load cited R/L table from configs (never invent)."""
    path = Path(repo_root) / "configs" / "circuit_dynamics_authority.json"
    if not path.is_file():
        raise PlannerReplanError(f"missing {path}")
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise PlannerReplanError("circuit_dynamics_authority must be object")
    return obj


def load_editable_passive(repo_root: Path) -> Dict[str, Any]:
    path = Path(repo_root) / "configs" / "passive_resistivity.json"
    if not path.is_file():
        return {
            "version": "1.1",
            "status": "awaiting_authority",
            "notes": "Populate components only with cited ρ.",
            "components": {},
        }
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise PlannerReplanError("passive_resistivity must be object")
    return obj


def apply_circuit_rl_edits(
    repo_root: Path,
    edits: Dict[str, Dict[str, Any]],
    *,
    citation_note: Optional[str] = None,
) -> Path:
    """Update R_ohm / L_henry for named circuits. Values must be > 0."""
    from .circuit_dynamics_authority import load_circuit_dynamics_authority

    path = Path(repo_root) / "configs" / "circuit_dynamics_authority.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    circuits = obj.get("circuits")
    if not isinstance(circuits, dict):
        raise PlannerReplanError("circuits missing")
    for name, vals in edits.items():
        if name not in circuits or not isinstance(circuits[name], dict):
            raise PlannerReplanError(f"unknown circuit {name!r} — cannot invent coils")
        if "R_ohm" in vals and vals["R_ohm"] is not None:
            r = float(vals["R_ohm"])
            if r <= 0:
                raise PlannerReplanError(f"{name}: R_ohm must be > 0")
            circuits[name]["R_ohm"] = r
        if "L_henry" in vals and vals["L_henry"] is not None:
            L = float(vals["L_henry"])
            if L <= 0:
                raise PlannerReplanError(f"{name}: L_henry must be > 0")
            circuits[name]["L_henry"] = L
    if citation_note and str(citation_note).strip():
        note = str(citation_note).strip()
        prev = str(obj.get("citation") or "")
        if note not in prev:
            obj["citation"] = (prev + " | " if prev else "") + f"UI edit: {note}"
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    load_circuit_dynamics_authority(path)
    return path


def apply_passive_resistivity_edits(
    repo_root: Path,
    components: Dict[str, Any],
    *,
    status: Optional[str] = None,
) -> Path:
    """Write passive ρ components — each needs resistivity_ohm_m > 0 and source."""
    from .passive_resistivity import load_passive_resistivity

    path = Path(repo_root) / "configs" / "passive_resistivity.json"
    obj = load_editable_passive(repo_root)
    clean: Dict[str, Any] = {}
    for name, entry in (components or {}).items():
        if not name or not isinstance(entry, dict):
            continue
        rho = entry.get("resistivity_ohm_m")
        src = entry.get("source")
        if rho is None and not src:
            continue
        if rho is None or float(rho) <= 0:
            raise PlannerReplanError(
                f"passive {name!r}: resistivity_ohm_m must be > 0 (never invent ρ)"
            )
        if not src or not str(src).strip():
            raise PlannerReplanError(f"passive {name!r}: source citation required")
        clean[str(name)] = {
            "resistivity_ohm_m": float(rho),
            "source": str(src).strip(),
        }
        if entry.get("notes"):
            clean[str(name)]["notes"] = str(entry["notes"])
    obj["components"] = clean
    if status:
        obj["status"] = str(status)
    elif clean:
        obj["status"] = "cited"
    else:
        obj["status"] = "awaiting_authority"
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    load_passive_resistivity(path)
    return path


def replan_shot(
    *,
    shot: int,
    repo_root: Path,
    config_path: Path,
    runs_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Re-run planner stage only against an existing SHOT/<N>/ (fail-closed)."""
    from .coil_limits import load_coil_limits, resolve_measured_peak_limits, write_coil_limits
    from .circuit_dynamics_authority import (
        build_circuit_dynamics_from_authority,
        load_circuit_dynamics_authority,
        write_circuit_dynamics_authority,
    )
    from .config import AppConfig
    from .planner import (
        extract_circuit_dynamics_from_freegsnke_machine,
        load_planner_authority,
        run_planner_stage,
        write_circuit_dynamics,
    )
    from .voltage_map import load_voltage_map

    repo_root = Path(repo_root).resolve()
    cfg = AppConfig.load(Path(config_path))
    runs = Path(runs_dir) if runs_dir else (repo_root / (cfg.runs_dir or "SHOT"))
    if not runs.is_absolute():
        runs = (repo_root / runs).resolve()
    run_dir = runs / str(int(shot))
    if not run_dir.is_dir():
        raise PlannerReplanError(f"missing run dir {run_dir} — reconstruct first")
    inputs = run_dir / "inputs"
    if not inputs.is_dir():
        raise PlannerReplanError(f"missing {inputs}")

    window_path = inputs / "window.json"
    if not window_path.is_file():
        raise PlannerReplanError("inputs/window.json required")
    window = json.loads(window_path.read_text(encoding="utf-8"))
    try:
        t0, t1 = float(window["t_start"]), float(window["t_end"])
    except (KeyError, TypeError, ValueError) as e:
        raise PlannerReplanError(f"inputs/window.json missing t_start/t_end: {e}") from e

    pl_path = Path(cfg.planner_authority_path or "configs/planner_authority.json")
    if not pl_path.is_absolute():
        pl_path = repo_root / pl_path
    lim_path = Path(cfg.coil_limits_authority_path or "configs/coil_limits_authority.json")
    if not lim_path.is_absolute():
        lim_path = repo_root / lim_path
    dyn_path = Path(cfg.circuit_dynamics_authority_path or "configs/circuit_dynamics_authority.json")
    if not dyn_path.is_absolute():
        dyn_path = repo_root / dyn_path
    vm_path = Path(cfg.voltage_map_path or "configs/voltage_map.json")
    if not vm_path.is_absolute():
        vm_path = repo_root / vm_path
    ma = Path(cfg.machine_authority_dir or "machine_authority")
    if not ma.is_absolute():
        ma = repo_root / ma
    if not ma.is_dir():
        raise PlannerReplanError(f"missing machine_authority_dir: {ma}")

    pl = load_planner_authority(pl_path)
    if not pl.enabled:
        raise PlannerReplanError("planner_authority.enabled=false")
    limits = load_coil_limits(lim_path)
    vm = load_voltage_map(vm_path)
    order = list(vm.machine_active_circuit_order)

    # Build dynamics first so measured-peak Vmax can use ohmic / RI+L dI/dt peaks
    dyn_auth = load_circuit_dynamics_authority(dyn_path)
    write_circuit_dynamics_authority(inputs, dyn_auth)
    try:
        fill = extract_circuit_dynamics_from_freegsnke_machine(
            machine_dir=ma, circuit_order=order
        )
    except Exception:
        fill = None
    dyn, dyn_meta = build_circuit_dynamics_from_authority(
        dyn_auth, circuit_order=order, freegsnke_fill=fill
    )
    write_circuit_dynamics(inputs / "circuit_dynamics_snapshot.json", dyn)

    import numpy as np

    R_for_limits = {
        name: float(r) for name, r in zip(dyn.circuit_order, np.asarray(dyn.R_ohm, dtype=float).ravel())
    }
    Lm = np.asarray(dyn.L_henry, dtype=float)
    diag = np.diag(Lm) if Lm.ndim == 2 else Lm.ravel()
    L_for_limits = {
        name: float(diag[i]) for i, name in enumerate(dyn.circuit_order) if i < len(diag)
    }

    lim_res = resolve_measured_peak_limits(
        limits,
        inputs_dir=inputs,
        circuit_order=order,
        t_start=t0,
        t_end=t1,
        R_ohm_by_circuit=R_for_limits or None,
        L_henry_by_circuit=L_for_limits or None,
        n_knots=int(pl.n_knots),
    )
    write_coil_limits(inputs, lim_res)

    st = None
    st_path = inputs / "shape_targets_authority" / "shape_targets.json"
    if st_path.is_file():
        try:
            st = json.loads(st_path.read_text(encoding="utf-8"))
        except Exception:
            st = None

    cache = Path(cfg.cache_dir or "data_cache")
    if not cache.is_absolute():
        cache = repo_root / cache
    cache_shot = cache / f"shot_{int(shot)}"

    out = run_planner_stage(
        run_dir=run_dir,
        inputs_dir=inputs,
        machine_dir=ma,
        planner_auth=pl,
        coil_limits=lim_res,
        circuit_order=order,
        t_start=t0,
        t_end=t1,
        shot=int(shot),
        circuit_dynamics=dyn,
        shape_targets=st if isinstance(st, dict) else None,
        cache_dir=cache_shot if cache_shot.is_dir() else cache,
    )
    return {
        "ok": True,
        "shot": int(shot),
        "planner": out,
        "dynamics_meta": dyn_meta,
        "passive_note": (
            "Passive ρ edits are saved to configs/passive_resistivity.json. "
            "Planner dynamics remain active-coil only until machine rebuild wires passives "
            "(Path B5). Rebuild machine_authority after citing ρ."
        ),
    }
