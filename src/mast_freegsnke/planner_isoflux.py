"""Path B2: vacuum-coil Green's response for GSPulse-style isoflux / x-point B costs.

Uses FreeGSNKE / freegs4e ``controlPsi`` / ``controlBr`` / ``controlBz`` on active
circuits — **vacuum (coil-only)** response. Plasma Picard contribution is Path B3.
Never invents probe positions: control points and x-points come from Path B1
``shape_targets`` (FAIR-MAST EFIT++ archive).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .planner import PlannerError


@dataclass(frozen=True)
class IsofluxSensors:
    """Linear vacuum sensors y = G @ I (+ optional plasma offset in target).

    Vacuum-only (B2): target ≈ 0.  Picard (B3): target = −plasma contribution so
    ``G @ I + plasma ≈ 0`` remains a linear QP sensor.
    """

    G: np.ndarray  # (n_sensors, n_circuits)
    target: np.ndarray  # (n_sensors,) — typically zeros for isoflux / null field
    labels: Tuple[str, ...]
    kind: str  # "isoflux_rel" | "xpoint_B" | "psi_bry_mean"
    r_m: np.ndarray
    z_m: np.ndarray
    note: str = ""
    # Full geometry for Picard plasma-offset rebuild (optional)
    r_all_m: Optional[np.ndarray] = None
    z_all_m: Optional[np.ndarray] = None
    ref_index: Optional[int] = None
    G_psi_full: Optional[np.ndarray] = None  # (n_points, n_circuits) before relative
    G_Br_full: Optional[np.ndarray] = None
    G_Bz_full: Optional[np.ndarray] = None


def _tokamak_from_machine(machine_dir: Path):
    machine_dir = Path(machine_dir)
    try:
        from freegsnke import build_machine  # type: ignore
    except Exception as e:
        raise PlannerError(
            "freegsnke not importable for isoflux Green's — run with FreeGSNKE env "
            f"or soft-skip isoflux. Import error: {type(e).__name__}: {e}"
        ) from e
    return build_machine.tokamak(
        active_coils_path=str(machine_dir / "active_coils.pickle"),
        passive_coils_path=str(machine_dir / "passive_coils.pickle"),
        limiter_path=str(machine_dir / "limiter.pickle"),
        wall_path=str(machine_dir / "wall.pickle"),
    )


def build_vacuum_coil_response(
    *,
    machine_dir: Path,
    circuit_order: Sequence[str],
    r_m: np.ndarray,
    z_m: np.ndarray,
    tokamak: Any = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (G_psi, G_Br, G_Bz) each shape (n_points, n_circuits)."""
    r = np.asarray(r_m, dtype=float).ravel()
    z = np.asarray(z_m, dtype=float).ravel()
    if r.size != z.size or r.size < 1:
        raise PlannerError("isoflux points: r_m/z_m must be non-empty and same length")
    if not (np.all(np.isfinite(r)) and np.all(np.isfinite(z))):
        raise PlannerError("isoflux points contain non-finite R/Z")
    if np.any(r <= 0):
        raise PlannerError("isoflux points require R > 0")
    order = [str(c) for c in circuit_order]
    tok = tokamak if tokamak is not None else _tokamak_from_machine(machine_dir)
    n = len(order)
    m = int(r.size)
    G_psi = np.zeros((m, n), dtype=float)
    G_Br = np.zeros((m, n), dtype=float)
    G_Bz = np.zeros((m, n), dtype=float)
    for j, name in enumerate(order):
        try:
            coil = tok[name]
        except Exception as e:
            raise PlannerError(f"machine missing circuit {name!r}: {e}") from e
        G_psi[:, j] = np.asarray(coil.controlPsi(r, z), dtype=float).ravel()
        G_Br[:, j] = np.asarray(coil.controlBr(r, z), dtype=float).ravel()
        G_Bz[:, j] = np.asarray(coil.controlBz(r, z), dtype=float).ravel()
    if not (np.all(np.isfinite(G_psi)) and np.all(np.isfinite(G_Br)) and np.all(np.isfinite(G_Bz))):
        raise PlannerError("vacuum Green's response contains non-finite values")
    return G_psi, G_Br, G_Bz


def _ref_index(r: np.ndarray, policy: str) -> int:
    policy = str(policy)
    if policy == "first_point":
        return 0
    if policy == "max_R":
        return int(np.argmax(r))
    raise PlannerError(f"unsupported isoflux_ref_policy {policy!r}")


def relative_flux_matrix(G_psi: np.ndarray, *, ref_index: int) -> np.ndarray:
    """Rows are G_i - G_ref (drop the ref row)."""
    G = np.asarray(G_psi, dtype=float)
    if not (0 <= ref_index < G.shape[0]):
        raise PlannerError("isoflux ref_index out of range")
    if G.shape[0] < 2:
        raise PlannerError("isoflux needs >= 2 control points for relative flux")
    G_rel = G - G[ref_index : ref_index + 1, :]
    keep = [i for i in range(G.shape[0]) if i != ref_index]
    return G_rel[keep, :]


def control_points_from_knot(knot: Dict[str, Any]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    cp = knot.get("control_points") if isinstance(knot, dict) else None
    if not isinstance(cp, dict):
        return None
    r = np.asarray(cp.get("r_m"), dtype=float).ravel()
    z = np.asarray(cp.get("z_m"), dtype=float).ravel()
    m = np.isfinite(r) & np.isfinite(z) & (r > 0)
    r, z = r[m], z[m]
    if r.size < 2:
        return None
    return r, z


def xpoints_from_knot(knot: Dict[str, Any]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    if not isinstance(knot, dict):
        return None
    scalars = knot.get("scalars") if isinstance(knot.get("scalars"), dict) else {}
    xr = scalars.get("x_point_r")
    xz = scalars.get("x_point_z")
    if xr is None or xz is None:
        return None
    rr = np.atleast_1d(np.asarray(xr, dtype=float)).ravel()
    zz = np.atleast_1d(np.asarray(xz, dtype=float)).ravel()
    n = min(rr.size, zz.size)
    rr, zz = rr[:n], zz[:n]
    m = np.isfinite(rr) & np.isfinite(zz) & (rr > 0)
    rr, zz = rr[m], zz[m]
    if rr.size < 1:
        return None
    return rr, zz


def build_isoflux_sensors_for_knots(
    *,
    machine_dir: Path,
    circuit_order: Sequence[str],
    shape_targets: Dict[str, Any],
    ref_policy: str = "max_R",
    max_control_points: int = 32,
) -> Dict[str, Any]:
    """Build per-knot vacuum isoflux + x-point B sensor packs from shape_targets payload."""
    if not isinstance(shape_targets, dict) or not shape_targets.get("present"):
        return {
            "ok": False,
            "status": "skipped_no_shape_targets",
            "mode": "vacuum_coil_greens",
            "knots": [],
            "note": "shape_targets missing/present=false — isoflux soft-skip",
        }
    knots_in = shape_targets.get("knots") or []
    if not isinstance(knots_in, list) or not knots_in:
        return {
            "ok": False,
            "status": "skipped_no_knots",
            "mode": "vacuum_coil_greens",
            "knots": [],
            "note": "shape_targets has no knots",
        }

    tok = _tokamak_from_machine(Path(machine_dir))
    order = [str(c) for c in circuit_order]
    out_knots: List[Dict[str, Any]] = []
    n_iso = 0
    n_xp = 0

    for knot in knots_in:
        entry: Dict[str, Any] = {
            "t_s": knot.get("t_s") if isinstance(knot, dict) else None,
            "isoflux": None,
            "xpoint_B": None,
        }
        cps = control_points_from_knot(knot if isinstance(knot, dict) else {})
        if cps is not None:
            r, z = cps
            if r.size > int(max_control_points):
                idx = np.linspace(0, r.size - 1, int(max_control_points)).astype(int)
                r, z = r[idx], z[idx]
            G_psi, _, _ = build_vacuum_coil_response(
                machine_dir=Path(machine_dir),
                circuit_order=order,
                r_m=r,
                z_m=z,
                tokamak=tok,
            )
            ref_i = _ref_index(r, ref_policy)
            G_rel = relative_flux_matrix(G_psi, ref_index=ref_i)
            labels = tuple(
                f"isoflux_pt{i}_minus_ref{ref_i}" for i in range(G_rel.shape[0])
            )
            keep_r = np.delete(r, ref_i)
            keep_z = np.delete(z, ref_i)
            entry["isoflux"] = IsofluxSensors(
                G=G_rel,
                target=np.zeros(G_rel.shape[0], dtype=float),
                labels=labels,
                kind="isoflux_rel",
                r_m=keep_r,
                z_m=keep_z,
                note=f"ref_policy={ref_policy} ref_index={ref_i} vacuum_coil_greens",
                r_all_m=r.copy(),
                z_all_m=z.copy(),
                ref_index=int(ref_i),
                G_psi_full=G_psi,
            )
            n_iso += 1

        xps = xpoints_from_knot(knot if isinstance(knot, dict) else {})
        if xps is not None:
            xr, xz = xps
            _, G_Br, G_Bz = build_vacuum_coil_response(
                machine_dir=Path(machine_dir),
                circuit_order=order,
                r_m=xr,
                z_m=xz,
                tokamak=tok,
            )
            # Stack Br then Bz for each x-point → target 0
            G_B = np.vstack([G_Br, G_Bz])
            labels = tuple(
                [f"Br_xp{i}" for i in range(xr.size)]
                + [f"Bz_xp{i}" for i in range(xr.size)]
            )
            entry["xpoint_B"] = IsofluxSensors(
                G=G_B,
                target=np.zeros(G_B.shape[0], dtype=float),
                labels=labels,
                kind="xpoint_B",
                r_m=np.concatenate([xr, xr]),
                z_m=np.concatenate([xz, xz]),
                note="vacuum_coil_greens Br/Bz→0 at archived x-point(s)",
                r_all_m=xr.copy(),
                z_all_m=xz.copy(),
                G_Br_full=G_Br,
                G_Bz_full=G_Bz,
            )
            n_xp += 1
        out_knots.append(entry)

    ok = n_iso > 0 or n_xp > 0
    return {
        "ok": ok,
        "status": "ok" if ok else "skipped_insufficient_geometry",
        "mode": "vacuum_coil_greens",
        "n_knots_with_isoflux": n_iso,
        "n_knots_with_xpoint_B": n_xp,
        "n_circuits": len(order),
        "circuit_order": order,
        "ref_policy": ref_policy,
        "knots": out_knots,
        "note": (
            "Vacuum (coil-only) Green's isoflux/x-point sensors from FreeGSNKE controlPsi/Br/Bz; "
            "plasma Picard contribution not included (Path B3)."
            if ok
            else "No LCFS control points or x-points available in shape_targets"
        ),
    }


def sensors_to_jsonable(pack: Dict[str, Any]) -> Dict[str, Any]:
    """Drop large G matrices from JSON; keep shapes + notes for provenance."""
    knots_out = []
    for k in pack.get("knots") or []:
        item: Dict[str, Any] = {"t_s": k.get("t_s")}
        for key in ("isoflux", "xpoint_B", "psi_bry"):
            sens = k.get(key)
            if isinstance(sens, IsofluxSensors):
                item[key] = {
                    "kind": sens.kind,
                    "n_sensors": int(sens.G.shape[0]),
                    "n_circuits": int(sens.G.shape[1]),
                    "labels": list(sens.labels),
                    "note": sens.note,
                    "target": [float(x) for x in np.asarray(sens.target).ravel()[:8]],
                    "r_m": [float(x) for x in np.asarray(sens.r_m).ravel()[:64]],
                    "z_m": [float(x) for x in np.asarray(sens.z_m).ravel()[:64]],
                }
            else:
                item[key] = None
        knots_out.append(item)
    return {
        "ok": pack.get("ok"),
        "status": pack.get("status"),
        "mode": pack.get("mode"),
        "n_knots_with_isoflux": pack.get("n_knots_with_isoflux"),
        "n_knots_with_xpoint_B": pack.get("n_knots_with_xpoint_B"),
        "circuit_order": pack.get("circuit_order"),
        "ref_policy": pack.get("ref_policy"),
        "note": pack.get("note"),
        "knots": knots_out,
    }


def evaluate_sensor_residuals(
    I: np.ndarray,
    pack: Dict[str, Any],
) -> Dict[str, Any]:
    """Compute RMS residuals for isoflux / x-point B under vacuum response."""
    I = np.asarray(I, dtype=float)
    n_t = I.shape[0]
    knots = pack.get("knots") or []
    iso_rms: List[float] = []
    xp_rms: List[float] = []
    psi_rms: List[float] = []
    for k in range(min(n_t, len(knots))):
        entry = knots[k]
        iso = entry.get("isoflux") if isinstance(entry, dict) else None
        if isinstance(iso, IsofluxSensors) and iso.G.shape[1] == I.shape[1]:
            y = iso.G @ I[k]
            e = y - iso.target
            iso_rms.append(float(np.sqrt(np.mean(e**2))))
        xp = entry.get("xpoint_B") if isinstance(entry, dict) else None
        if isinstance(xp, IsofluxSensors) and xp.G.shape[1] == I.shape[1]:
            y = xp.G @ I[k]
            e = y - xp.target
            xp_rms.append(float(np.sqrt(np.mean(e**2))))
        pb = entry.get("psi_bry") if isinstance(entry, dict) else None
        if isinstance(pb, IsofluxSensors) and pb.G.shape[1] == I.shape[1]:
            y = pb.G @ I[k]
            e = y - pb.target
            psi_rms.append(float(np.sqrt(np.mean(e**2))))
    return {
        "isoflux_rms_mean": float(np.mean(iso_rms)) if iso_rms else None,
        "isoflux_rms_max": float(np.max(iso_rms)) if iso_rms else None,
        "xpoint_B_rms_mean": float(np.mean(xp_rms)) if xp_rms else None,
        "xpoint_B_rms_max": float(np.max(xp_rms)) if xp_rms else None,
        "psi_bry_rms_mean": float(np.mean(psi_rms)) if psi_rms else None,
        "psi_bry_rms_max": float(np.max(psi_rms)) if psi_rms else None,
        "n_knots_scored_isoflux": len(iso_rms),
        "n_knots_scored_xpoint_B": len(xp_rms),
        "n_knots_scored_psi_bry": len(psi_rms),
    }
