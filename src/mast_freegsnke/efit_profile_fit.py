"""EFIT++ archive → declared ConstrainPaxisIp profile trajectory (ADR-004 Phase 1 / Idea E).

Never invents missing archive fields. Soft-skips when require=false and inputs insufficient.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .profile_trajectory import (
    ProfileKnot,
    ProfileTrajectory,
    ProfileTrajectoryPolicy,
    knot_times_linspace,
    load_profile_trajectory_policy,
    write_profile_trajectory,
    write_profile_trajectory_policy,
)
from .util import sha256_file


class ProfileFitError(RuntimeError):
    """Blocking fit failure when require=true or internal invariant broken."""


@dataclass(frozen=True)
class ProfileRef:
    paxis_Pa: float
    fvac: float
    alpha_m: float
    alpha_n: float


def _inventory_vars(ds: Any) -> List[str]:
    names = set(getattr(ds, "data_vars", {}) or {})
    names |= set(getattr(ds, "coords", {}) or {})
    return sorted(str(n) for n in names)


def _first_present(ds: Any, candidates: Sequence[str]) -> Optional[str]:
    for c in candidates:
        if c in ds:
            return str(c)
    return None


def _series_1d(ds: Any, name: str) -> Optional[np.ndarray]:
    if name not in ds:
        return None
    da = ds[name]
    vals = np.asarray(da.values, dtype=float)
    if vals.ndim == 1:
        return vals
    dims = list(getattr(da, "dims", ()))
    if "time" in dims:
        t_axis = dims.index("time")
        # collapse non-time dims by taking first index
        slicer: List[Any] = []
        for i, d in enumerate(dims):
            if i == t_axis:
                slicer.append(slice(None))
            else:
                slicer.append(0)
        return np.asarray(da.values[tuple(slicer)], dtype=float).reshape(-1)
    return vals.reshape(vals.shape[0], -1)[:, 0]


def _profile_at_time(
    ds: Any,
    *,
    t_idx: int,
    var_name: str,
    psi_n_name: Optional[str],
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Return (psi_n, profile) at time index, or None if unusable."""
    if var_name not in ds:
        return None
    da = ds[var_name]
    vals = np.asarray(da.values, dtype=float)
    dims = list(getattr(da, "dims", ()))
    if vals.ndim == 1:
        y = vals
    elif "time" in dims:
        t_axis = dims.index("time")
        y = np.take(vals, t_idx, axis=t_axis)
        y = np.asarray(y, dtype=float).ravel()
    else:
        y = np.asarray(vals[t_idx] if vals.shape[0] > t_idx else vals[0], dtype=float).ravel()

    if psi_n_name and psi_n_name in ds:
        pn_da = ds[psi_n_name]
        pn = np.asarray(pn_da.values, dtype=float)
        pn_dims = list(getattr(pn_da, "dims", ()))
        if "time" in pn_dims and pn.ndim >= 2:
            pn = np.take(pn, t_idx, axis=pn_dims.index("time"))
        pn = np.asarray(pn, dtype=float).ravel()
        n = min(pn.size, y.size)
        pn, y = pn[:n], y[:n]
    else:
        # assume uniform psi_n on [0,1] along profile length — labeled in provenance
        pn = np.linspace(0.0, 1.0, y.size)

    m = np.isfinite(pn) & np.isfinite(y)
    if m.sum() < 5:
        return None
    pn, y = pn[m], y[m]
    order = np.argsort(pn)
    return pn[order], y[order]


def _constrain_paxis_shape(psi_n: np.ndarray, alpha_m: float, alpha_n: float) -> np.ndarray:
    """Unit-peak Lao-like p' shape used by ConstrainPaxisIp-style bases: (1-ψ^α_m)^α_n."""
    psi_n = np.clip(np.asarray(psi_n, dtype=float), 0.0, 1.0)
    am = float(alpha_m)
    an = float(alpha_n)
    base = np.clip(1.0 - np.power(psi_n, am), 0.0, None)
    return np.power(base, an)


def _fit_alphas_to_profile(
    psi_n: np.ndarray,
    y: np.ndarray,
    *,
    alpha_m0: float,
    alpha_n0: float,
) -> Tuple[float, float, float, float]:
    """Fit alpha_m, alpha_n; return (alpha_m, alpha_n, scale, rms).

    scale is such that model ≈ scale * shape ≈ y (scale ~ paxis when y is pprime).
    """
    peak = float(np.nanmax(np.abs(y)))
    if not (peak > 0.0):
        return float(alpha_m0), float(alpha_n0), 0.0, float("nan")
    y_n = y / peak

    best = (float(alpha_m0), float(alpha_n0), float("inf"))
    # Coarse grid around IC alphas — deterministic, no hidden optimizer package required.
    am_grid = np.unique(
        np.clip(
            np.concatenate(
                [
                    [alpha_m0],
                    np.linspace(max(0.2, alpha_m0 * 0.5), alpha_m0 * 1.5, 9),
                    np.linspace(0.5, 3.0, 8),
                ]
            ),
            0.2,
            5.0,
        )
    )
    an_grid = np.unique(
        np.clip(
            np.concatenate(
                [
                    [alpha_n0],
                    np.linspace(max(0.2, alpha_n0 * 0.5), alpha_n0 * 1.5, 9),
                    np.linspace(0.5, 3.0, 8),
                ]
            ),
            0.2,
            5.0,
        )
    )
    for am in am_grid:
        for an in an_grid:
            shape = _constrain_paxis_shape(psi_n, float(am), float(an))
            smax = float(np.nanmax(shape))
            if not (smax > 0.0):
                continue
            shape_n = shape / smax
            rms = float(np.sqrt(np.nanmean((y_n - shape_n) ** 2)))
            if rms < best[2]:
                best = (float(am), float(an), rms)

    am_f, an_f, rms_f = best
    shape = _constrain_paxis_shape(psi_n, am_f, an_f)
    # Least-squares scale against raw y
    denom = float(np.nansum(shape * shape))
    scale = float(np.nansum(shape * y) / denom) if denom > 0.0 else peak
    if not (scale > 0.0):
        scale = peak
    return am_f, an_f, scale, rms_f


def load_profile_ref_from_execution_authority(inputs_dir: Path) -> ProfileRef:
    path = Path(inputs_dir) / "execution_authority" / "profile_spec.json"
    if not path.exists():
        # Bundle file
        bundle = Path(inputs_dir) / "execution_authority" / "execution_authority_bundle.json"
        if bundle.exists():
            obj = json.loads(bundle.read_text(encoding="utf-8"))
            prof = obj.get("profile") or {}
        else:
            raise ProfileFitError(
                "execution_authority profile_spec.json missing — write execution authority before profile fit"
            )
    else:
        prof = json.loads(path.read_text(encoding="utf-8"))
    ref = ProfileRef(
        paxis_Pa=float(prof["paxis_Pa"]),
        fvac=float(prof["fvac"]),
        alpha_m=float(prof["alpha_m"]),
        alpha_n=float(prof["alpha_n"]),
    )
    if not (ref.paxis_Pa > 0.0 and ref.alpha_m > 0.0 and ref.alpha_n > 0.0):
        raise ProfileFitError("execution_authority profile_spec has non-positive paxis/alphas")
    if not (0.0 <= ref.fvac <= 1.0):
        raise ProfileFitError("execution_authority profile_spec fvac out of [0,1]")
    return ref


def _load_window(inputs_dir: Path) -> Tuple[float, float]:
    win_path = Path(inputs_dir) / "window.json"
    if not win_path.exists():
        raise ProfileFitError("inputs/window.json missing — need formed-plasma window for knots")
    win = json.loads(win_path.read_text(encoding="utf-8"))
    t_start = float(win["t_start"])
    t_end = float(win["t_end"])
    if not (t_end > t_start):
        raise ProfileFitError(f"invalid window: t_end={t_end} must be > t_start={t_start}")
    return t_start, t_end


def _open_eq(cache_dir: Path, group: str) -> Any:
    from .efit_compare import _open_equilibrium, _time_coord, _nearest_index  # reuse ADR-002 helpers

    ds = _open_equilibrium(cache_dir, group)
    times = _time_coord(ds)
    return ds, times, _nearest_index


def build_profile_trajectory_from_efit(
    *,
    inputs_dir: Path,
    cache_dir: Path,
    policy: ProfileTrajectoryPolicy,
    shot: Optional[int] = None,
) -> ProfileTrajectory:
    """Fit or soft-skip a profile trajectory from FAIR-MAST equilibrium archive."""
    policy.validate()
    inputs_dir = Path(inputs_dir)
    cache_dir = Path(cache_dir)

    if not policy.enabled:
        return ProfileTrajectory(
            authority_name=policy.authority_name,
            authority_version=policy.authority_version,
            basis_type=policy.basis_type,
            fit_mode_used="none",
            interpolation=policy.interpolation,
            status="awaiting_authority",
            knots=[],
            provenance={"reason": "policy.enabled=false"},
            notes=policy.notes,
        )

    try:
        ref = load_profile_ref_from_execution_authority(inputs_dir)
        t_start, t_end = _load_window(inputs_dir)
        knot_t = knot_times_linspace(t_start, t_end, int(policy.n_knots))
    except ProfileFitError as e:
        if policy.require:
            raise
        return ProfileTrajectory(
            authority_name=policy.authority_name,
            authority_version=policy.authority_version,
            basis_type=policy.basis_type,
            fit_mode_used="none",
            interpolation=policy.interpolation,
            status="skipped_insufficient_archive",
            knots=[],
            provenance={"reason": str(e)},
            notes=policy.notes,
        )

    try:
        ds, times, nearest_index = _open_eq(cache_dir, policy.equilibrium_group)
    except Exception as e:
        if policy.require:
            raise ProfileFitError(
                f"equilibrium archive unavailable: {e}. "
                "Download optional_groups 'equilibrium' or set require=false."
            ) from e
        return ProfileTrajectory(
            authority_name=policy.authority_name,
            authority_version=policy.authority_version,
            basis_type=policy.basis_type,
            fit_mode_used="none",
            interpolation=policy.interpolation,
            status="skipped_insufficient_archive",
            knots=[],
            provenance={"reason": f"equilibrium_unavailable:{type(e).__name__}:{e}"},
            notes=policy.notes,
        )

    inventory = _inventory_vars(ds)
    pprime_name = _first_present(ds, policy.pprime_vars)
    ffprime_name = _first_present(ds, policy.ffprime_vars)
    psi_n_name = _first_present(ds, policy.psi_n_vars)
    wmhd = _series_1d(ds, policy.wmhd_var)

    mode = policy.fit_mode
    if mode == "auto":
        if pprime_name is not None:
            mode = "archive_profiles"
        elif wmhd is not None and np.isfinite(wmhd).any():
            mode = "scalar_bridge"
        else:
            mode = "none"

    zpath = Path(cache_dir) / f"{policy.equilibrium_group}.zarr"
    eq_hash = None
    try:
        # Hash a small marker file if present; else skip
        marker = zpath / ".zgroup"
        if marker.exists():
            eq_hash = sha256_file(marker)
    except Exception:
        eq_hash = None

    provenance: Dict[str, Any] = {
        "shot": shot,
        "equilibrium_path": str(zpath),
        "equilibrium_zgroup_sha256": eq_hash,
        "field_inventory": inventory,
        "pprime_var": pprime_name,
        "ffprime_var": ffprime_name,
        "psi_n_var": psi_n_name,
        "wmhd_var": policy.wmhd_var if wmhd is not None else None,
        "fit_mode_requested": policy.fit_mode,
        "fit_mode_used": mode,
        "profile_ref": {
            "paxis_Pa": ref.paxis_Pa,
            "fvac": ref.fvac,
            "alpha_m": ref.alpha_m,
            "alpha_n": ref.alpha_n,
            "source": "execution_authority/profile_spec.json",
        },
        "t_start": float(t_start),
        "t_end": float(t_end),
        "n_knots": int(policy.n_knots),
        "scalar_bridge_formula": policy.scalar_bridge_formula,
    }

    if mode == "none":
        if policy.require:
            raise ProfileFitError(
                "profile_trajectory require=true but archive lacks pprime/wmhd for fit; "
                f"inventory={inventory[:40]}"
            )
        return ProfileTrajectory(
            authority_name=policy.authority_name,
            authority_version=policy.authority_version,
            basis_type=policy.basis_type,
            fit_mode_used="none",
            interpolation=policy.interpolation,
            status="skipped_insufficient_archive",
            knots=[],
            provenance=provenance,
            notes=policy.notes,
        )

    knots: List[ProfileKnot] = []

    if mode == "scalar_bridge":
        if wmhd is None or not np.isfinite(wmhd).any():
            if policy.require:
                raise ProfileFitError(
                    f"scalar_bridge requires finite '{policy.wmhd_var}' in equilibrium archive"
                )
            return ProfileTrajectory(
                authority_name=policy.authority_name,
                authority_version=policy.authority_version,
                basis_type=policy.basis_type,
                fit_mode_used="scalar_bridge",
                interpolation=policy.interpolation,
                status="skipped_insufficient_archive",
                knots=[],
                provenance={**provenance, "reason": "wmhd_missing_or_all_nan"},
                notes=policy.notes,
            )
        # Reference wmhd: first finite sample nearest to first knot (or any finite)
        wmhd_at_knots: List[float] = []
        for t in knot_t:
            idx = nearest_index(times, float(t))
            w = float(wmhd[idx]) if idx < len(wmhd) else float("nan")
            wmhd_at_knots.append(w)
        finite_w = [w for w in wmhd_at_knots if np.isfinite(w) and w > 0.0]
        if not finite_w:
            if policy.require:
                raise ProfileFitError("scalar_bridge: no positive finite wmhd at knot times")
            return ProfileTrajectory(
                authority_name=policy.authority_name,
                authority_version=policy.authority_version,
                basis_type=policy.basis_type,
                fit_mode_used="scalar_bridge",
                interpolation=policy.interpolation,
                status="skipped_insufficient_archive",
                knots=[],
                provenance={**provenance, "reason": "wmhd_nonpositive_at_knots"},
                notes=policy.notes,
            )
        wmhd_ref = float(finite_w[0])
        provenance["wmhd_ref"] = wmhd_ref
        for t, w in zip(knot_t, wmhd_at_knots):
            if not (np.isfinite(w) and w > 0.0):
                if policy.require:
                    raise ProfileFitError(f"scalar_bridge: wmhd missing at t={t}")
                continue
            paxis = float(ref.paxis_Pa) * (float(w) / wmhd_ref)
            knots.append(
                ProfileKnot(
                    t_s=float(t),
                    paxis_Pa=paxis,
                    fvac=float(ref.fvac),
                    alpha_m=float(ref.alpha_m),
                    alpha_n=float(ref.alpha_n),
                    residual={"wmhd": float(w), "wmhd_ratio": float(w) / wmhd_ref},
                )
            )

    elif mode == "archive_profiles":
        if pprime_name is None:
            if policy.require:
                raise ProfileFitError("archive_profiles requires a pprime-like variable")
            return ProfileTrajectory(
                authority_name=policy.authority_name,
                authority_version=policy.authority_version,
                basis_type=policy.basis_type,
                fit_mode_used="archive_profiles",
                interpolation=policy.interpolation,
                status="skipped_insufficient_archive",
                knots=[],
                provenance={**provenance, "reason": "pprime_missing"},
                notes=policy.notes,
            )
        provenance["psi_n_assumption"] = (
            None if psi_n_name else "linspace_0_1_along_profile_length"
        )
        for t in knot_t:
            idx = nearest_index(times, float(t))
            pair = _profile_at_time(ds, t_idx=idx, var_name=pprime_name, psi_n_name=psi_n_name)
            if pair is None:
                if policy.require:
                    raise ProfileFitError(f"archive_profiles: unusable pprime at t={t}")
                continue
            psi_n, y = pair
            am, an, scale, rms = _fit_alphas_to_profile(
                psi_n, y, alpha_m0=ref.alpha_m, alpha_n0=ref.alpha_n
            )
            fvac = float(ref.fvac)
            ff_rms = None
            if ffprime_name is not None:
                ff_pair = _profile_at_time(
                    ds, t_idx=idx, var_name=ffprime_name, psi_n_name=psi_n_name
                )
                if ff_pair is not None:
                    # Keep fvac from authority; record ffprime fit residual only (fvac basis differs).
                    _, ff_y = ff_pair
                    shape = _constrain_paxis_shape(ff_pair[0], am, an)
                    denom = float(np.nansum(shape * shape))
                    if denom > 0.0:
                        ff_scale = float(np.nansum(shape * ff_y) / denom)
                        pred = ff_scale * shape
                        ff_rms = float(np.sqrt(np.nanmean((ff_y - pred) ** 2)))
            if not (scale > 0.0):
                if policy.require:
                    raise ProfileFitError(f"archive_profiles: non-positive paxis scale at t={t}")
                continue
            knots.append(
                ProfileKnot(
                    t_s=float(t),
                    paxis_Pa=float(scale),
                    fvac=fvac,
                    alpha_m=float(am),
                    alpha_n=float(an),
                    residual={
                        "alphas_source": "efit_pprime_fit",
                        "pprime_rms_norm": float(rms),
                        **({"ffprime_rms": float(ff_rms)} if ff_rms is not None else {}),
                    },
                )
            )
    else:
        raise ProfileFitError(f"unknown fit mode: {mode}")

    if len(knots) < 2:
        if policy.require:
            raise ProfileFitError(
                f"profile_trajectory require=true but only {len(knots)} usable knots "
                f"(need >= 2); mode={mode}"
            )
        return ProfileTrajectory(
            authority_name=policy.authority_name,
            authority_version=policy.authority_version,
            basis_type=policy.basis_type,
            fit_mode_used=mode,
            interpolation=policy.interpolation,
            status="skipped_insufficient_archive",
            knots=[],
            provenance={**provenance, "reason": f"insufficient_knots:{len(knots)}"},
            notes=policy.notes,
        )

    return ProfileTrajectory(
        authority_name=policy.authority_name,
        authority_version=policy.authority_version,
        basis_type=policy.basis_type,
        fit_mode_used=mode,
        interpolation=policy.interpolation,
        status="ok",
        knots=knots,
        provenance=provenance,
        notes=policy.notes,
    )


def run_profile_trajectory_stage(
    *,
    inputs_dir: Path,
    cache_dir: Path,
    policy_path: Path,
    shot: Optional[int] = None,
    policy: Optional[ProfileTrajectoryPolicy] = None,
) -> Dict[str, Any]:
    """Load policy, fit, snapshot policy+trajectory; return stage report dict."""
    pol = policy if policy is not None else load_profile_trajectory_policy(policy_path)
    write_profile_trajectory_policy(inputs_dir, pol)
    traj = build_profile_trajectory_from_efit(
        inputs_dir=inputs_dir,
        cache_dir=cache_dir,
        policy=pol,
        shot=shot,
    )
    out_path = write_profile_trajectory(inputs_dir, traj)
    return {
        "ok": traj.status == "ok",
        "status": traj.status,
        "fit_mode_used": traj.fit_mode_used,
        "n_knots": len(traj.knots),
        "path": str(out_path),
        "require": bool(pol.require),
        "enabled": bool(pol.enabled),
        "content_sha256": traj.content_sha256() if traj.status == "ok" else None,
        "provenance": traj.provenance,
        "fix_hint": (
            None
            if traj.status == "ok"
            else (
                "Ensure FAIR-MAST optional group 'equilibrium' is downloaded and contains "
                f"'{pol.wmhd_var}' and/or pprime-like profiles; or set require=false "
                "(evolutive will hold inverse IC profiles)."
            )
        ),
    }
