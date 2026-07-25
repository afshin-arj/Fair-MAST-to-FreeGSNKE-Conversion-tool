"""Extract / persist FreeGSNKE LCFS polylines — never invent geometry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


def lcfs_arrays_from_eq(eq: Any) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Best-effort LCFS (R, Z) from a solved FreeGSNKE/freegs Equilibrium."""
    for r_name, z_name in (
        ("rboundary", "zboundary"),
        ("Rbound", "Zbound"),
        ("R_boundary", "Z_boundary"),
    ):
        r = getattr(eq, r_name, None)
        z = getattr(eq, z_name, None)
        if r is None or z is None:
            continue
        rr = np.asarray(r, dtype=float).ravel()
        zz = np.asarray(z, dtype=float).ravel()
        m = np.isfinite(rr) & np.isfinite(zz)
        if int(m.sum()) >= 3:
            return rr[m], zz[m]

    sep = getattr(eq, "separatrix", None)
    if callable(sep):
        for kwargs in ({"ntheta": 201}, {}):
            try:
                raw = sep(**kwargs) if kwargs else sep()
            except TypeError:
                try:
                    raw = sep()
                except Exception:
                    continue
            except Exception:
                continue
            arr = np.asarray(raw, dtype=float)
            if arr.ndim == 2 and arr.shape[0] == 2 and arr.shape[1] >= 3:
                rr, zz = arr[0], arr[1]
            elif arr.ndim == 2 and arr.shape[1] == 2 and arr.shape[0] >= 3:
                rr, zz = arr[:, 0], arr[:, 1]
            else:
                continue
            m = np.isfinite(rr) & np.isfinite(zz)
            if int(m.sum()) >= 3:
                return rr[m], zz[m]
    return None


def write_freegsnke_lcfs_csv(
    path: Path,
    r: np.ndarray,
    z: np.ndarray,
    *,
    time_s: Optional[float] = None,
) -> Path:
    """Write static LCFS CSV (columns R, Z[, time])."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, Any] = {
        "R": np.asarray(r, dtype=float).ravel(),
        "Z": np.asarray(z, dtype=float).ravel(),
    }
    if time_s is not None and np.isfinite(float(time_s)):
        data["time"] = np.full(data["R"].shape, float(time_s), dtype=float)
    pd.DataFrame(data).to_csv(path, index=False)
    return path


def write_freegsnke_lcfs_timeseries_csv(
    path: Path,
    rows: Sequence[Dict[str, Any]],
) -> Optional[Path]:
    """Write multi-time LCFS as long-form CSV: time,R,Z."""
    path = Path(path)
    out_rows: List[Dict[str, float]] = []
    for row in rows:
        t = row.get("t")
        rr = np.asarray(row.get("R"), dtype=float).ravel()
        zz = np.asarray(row.get("Z"), dtype=float).ravel()
        if t is None or not np.isfinite(float(t)):
            continue
        m = np.isfinite(rr) & np.isfinite(zz)
        if int(m.sum()) < 3:
            continue
        for r_i, z_i in zip(rr[m], zz[m]):
            out_rows.append({"time": float(t), "R": float(r_i), "Z": float(z_i)})
    if not out_rows:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(out_rows).to_csv(path, index=False)
    return path


def lcfs_from_dump_dict(dump: Dict[str, Any]) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Read lcfs_R / lcfs_Z arrays persisted in inverse_dump.pkl."""
    if not isinstance(dump, dict):
        return None
    r = dump.get("lcfs_R")
    z = dump.get("lcfs_Z")
    if r is None or z is None:
        return None
    rr = np.asarray(r, dtype=float).ravel()
    zz = np.asarray(z, dtype=float).ravel()
    m = np.isfinite(rr) & np.isfinite(zz)
    if int(m.sum()) < 3:
        return None
    return rr[m], zz[m]


def psi_pack_from_dump(dump: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return ψ + R/Z meshes from inverse_dump for EFIT side-by-side.

    Prefers ``total_psi`` (``eq.psi()`` = plasma + coils) so the left panel matches
    FAIR-MAST EFIT++ archive total ψ. Falls back to ``plasma_psi`` only with
    ``kind="plasma_psi"`` — callers should not treat that as amplitude-comparable
    to EFIT total ψ.
    """
    if not isinstance(dump, dict):
        return None
    grid = dump.get("grid")
    if not isinstance(grid, dict):
        return None
    R = np.asarray(grid.get("R"), dtype=float)
    Z = np.asarray(grid.get("Z"), dtype=float)
    if R.size < 4 or Z.size < 4:
        return None
    psi = dump.get("total_psi")
    kind = "total_psi"
    if psi is None and dump.get("psi") is not None:
        # Some dumps may store total flux as "psi"
        psi = dump.get("psi")
        kind = "total_psi"
    if psi is None:
        psi = dump.get("plasma_psi")
        kind = "plasma_psi"
    if psi is None:
        return None
    field = np.asarray(psi, dtype=float)
    if field.size < 4:
        return None
    return {
        "psi": field,
        "R": R,
        "Z": Z,
        "t0": dump.get("t0"),
        "kind": kind,
        "comparable_to_efit_total_psi": kind == "total_psi",
    }


def plasma_psi_pack_from_dump(dump: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Backward-compatible alias; prefer :func:`psi_pack_from_dump`."""
    return psi_pack_from_dump(dump)


def load_inverse_dump(run_dir: Path) -> Optional[Dict[str, Any]]:
    for rel in ("inverse_dump.pkl", "03_reconstruction/inverse_dump.pkl"):
        p = Path(run_dir) / rel
        if not p.is_file():
            continue
        try:
            import pickle

            obj = pickle.loads(p.read_bytes())
        except Exception:
            continue
        if isinstance(obj, dict):
            return obj
    return None


def freegsnke_lcfs_csv_candidates(run_dir: Path) -> List[Path]:
    """Prefer forward-replay LCFS, then paths written by :func:`persist_lcfs_from_eq`."""
    run_dir = Path(run_dir)
    return [
        run_dir / "04_efit_compare" / "forward_replay" / "freegsnke_forward_replay_lcfs.csv",
        run_dir / "presentation" / "freegsnke_lcfs.csv",
        run_dir / "03_reconstruction" / "presentation" / "freegsnke_lcfs.csv",
        run_dir / "03_reconstruction" / "freegsnke_lcfs.csv",
        run_dir / "synthetic" / "freegsnke_lcfs.csv",
        run_dir / "03_reconstruction" / "synthetic" / "freegsnke_lcfs.csv",
        run_dir / "freegsnke_lcfs.csv",
    ]


def freegsnke_lcfs_timeseries_candidates(run_dir: Path) -> List[Path]:
    run_dir = Path(run_dir)
    return [
        run_dir / "presentation" / "freegsnke_lcfs_timeseries.csv",
        run_dir / "03_reconstruction" / "presentation" / "freegsnke_lcfs_timeseries.csv",
        run_dir / "03_reconstruction" / "freegsnke_lcfs_timeseries.csv",
        run_dir / "freegsnke_lcfs_timeseries.csv",
    ]


def freegsnke_t0_from_run(run_dir: Path) -> Optional[float]:
    """Inverse solve time from dump or LCFS CSV ``time`` column — never invent."""
    dump = load_inverse_dump(Path(run_dir))
    if dump is not None:
        t0 = dump.get("t0")
        try:
            if t0 is not None and np.isfinite(float(t0)):
                return float(t0)
        except (TypeError, ValueError):
            pass
    for p in freegsnke_lcfs_csv_candidates(Path(run_dir)):
        if not p.is_file():
            continue
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        cols = {c.lower(): c for c in df.columns}
        if "time" not in cols:
            continue
        tt = df[cols["time"]].to_numpy(dtype=float)
        finite = tt[np.isfinite(tt)]
        if finite.size:
            return float(finite[0])
    return None


def lcfs_at_time_from_timeseries(
    run_dir: Path, t: float
) -> Optional[Tuple[Tuple[np.ndarray, np.ndarray], float, str]]:
    """Nearest FreeGSNKE LCFS from timeseries CSV to ``t``.

    Returns ``((R,Z), t_used, source_path)`` or None.
    """
    for p in freegsnke_lcfs_timeseries_candidates(Path(run_dir)):
        if not p.is_file():
            continue
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        cols = {c.lower(): c for c in df.columns}
        if "time" not in cols or "r" not in cols or "z" not in cols:
            continue
        times = sorted({float(x) for x in df[cols["time"]].to_numpy(dtype=float) if np.isfinite(x)})
        if not times:
            continue
        t_used = min(times, key=lambda x: abs(x - float(t)))
        g = df[np.isclose(df[cols["time"]].to_numpy(dtype=float), t_used)]
        rr = g[cols["r"]].to_numpy(dtype=float)
        zz = g[cols["z"]].to_numpy(dtype=float)
        m = np.isfinite(rr) & np.isfinite(zz)
        if int(m.sum()) < 3:
            continue
        return (rr[m], zz[m]), float(t_used), str(p.as_posix())
    return None


def read_lcfs_csv(path: Path) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    cols = {c.lower(): c for c in df.columns}
    if "r" not in cols or "z" not in cols:
        return None
    rr = df[cols["r"]].to_numpy(dtype=float)
    zz = df[cols["z"]].to_numpy(dtype=float)
    m = np.isfinite(rr) & np.isfinite(zz)
    if int(m.sum()) < 3:
        return None
    return rr[m], zz[m]


def persist_lcfs_from_eq(
    run_dir: Path,
    eq: Any,
    *,
    time_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Write freegsnke_lcfs.csv under presentation/ (junction-friendly)."""
    out: Dict[str, Any] = {"ok": False, "paths": [], "n_points": 0}
    lcfs = lcfs_arrays_from_eq(eq)
    if lcfs is None:
        out["error"] = "lcfs_extract_failed"
        return out
    rr, zz = lcfs
    out["n_points"] = int(len(rr))
    run_dir = Path(run_dir)
    targets = [
        run_dir / "presentation" / "freegsnke_lcfs.csv",
        run_dir / "03_reconstruction" / "presentation" / "freegsnke_lcfs.csv",
        run_dir / "03_reconstruction" / "freegsnke_lcfs.csv",
    ]
    # Prefer presentation/ (shot layout junctions); also write expert path if distinct
    written: List[str] = []
    primary = targets[0]
    write_freegsnke_lcfs_csv(primary, rr, zz, time_s=time_s)
    written.append(str(primary.as_posix()))
    for alt in targets[1:]:
        try:
            if alt.resolve() != primary.resolve():
                write_freegsnke_lcfs_csv(alt, rr, zz, time_s=time_s)
                written.append(str(alt.as_posix()))
        except Exception:
            pass
    meta = {
        "n_points": int(len(rr)),
        "time_s": float(time_s) if time_s is not None and np.isfinite(float(time_s)) else None,
        "source": "eq.separatrix_or_rboundary",
    }
    meta_path = primary.parent / "freegsnke_lcfs_meta.json"
    try:
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass
    out["ok"] = True
    out["paths"] = written
    out["R"] = rr
    out["Z"] = zz
    return out


def recover_lcfs_via_freegsnke_venv(
    run_dir: Path,
    *,
    machine_dir: Path,
    freegsnke_python: Optional[str] = None,
    repo_root: Optional[Path] = None,
    timeout_s: float = 300.0,
) -> Dict[str, Any]:
    """Rebuild IC from inverse_dump in FreeGSNKE venv and persist LCFS CSV + dump arrays.

    Used when older dumps lack ``lcfs_R`` / CSV products. Never invents geometry.
    """
    import os
    import subprocess
    import sys

    from .freegsnke_runner import resolve_freegsnke_python

    run_dir = Path(run_dir).resolve()
    machine_dir = Path(machine_dir).resolve()
    root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[2]
    report: Dict[str, Any] = {"ok": False, "errors": [], "paths": []}
    dump_path = run_dir / "inverse_dump.pkl"
    if not dump_path.is_file():
        report["errors"].append("missing_inverse_dump")
        return report
    if not machine_dir.is_dir():
        report["errors"].append(f"missing_machine_dir:{machine_dir}")
        return report
    py = resolve_freegsnke_python(freegsnke_python, root) if freegsnke_python else sys.executable
    rd = str(run_dir)
    md = str(machine_dir)
    script = f"""
import pickle
from pathlib import Path
import numpy as np
from freegsnke import build_machine, equilibrium_update, GSstaticsolver
from freegsnke.jtor_update import ConstrainPaxisIp
from mast_freegsnke.freegsnke_lcfs import lcfs_arrays_from_eq, persist_lcfs_from_eq
HERE = Path({rd!r})
MACHINE = Path({md!r})
dump = pickle.loads((HERE / "inverse_dump.pkl").read_bytes())
if not isinstance(dump, dict):
    raise SystemExit("dump_not_dict")
ea = dump.get("execution_authority_bundle") or {{}}
grid = ea.get("grid") or {{}}
tokamak = build_machine.tokamak(
    active_coils_path=str(MACHINE / "active_coils.pickle"),
    passive_coils_path=str(MACHINE / "passive_coils.pickle"),
    limiter_path=str(MACHINE / "limiter.pickle"),
    wall_path=str(MACHINE / "wall.pickle"),
)
curr = dump.get("coil_currents") or {{}}
for name, coil in getattr(tokamak, "coils", []):
    if name in curr and hasattr(coil, "current"):
        coil.current = float(curr[name])
eq = equilibrium_update.Equilibrium(
    tokamak=tokamak,
    Rmin=float(grid["Rmin"]),
    Rmax=float(grid["Rmax"]),
    Zmin=float(grid["Zmin"]),
    Zmax=float(grid["Zmax"]),
    nx=int(grid["nx"]),
    ny=int(grid["ny"]),
)
pk = dump["profile_kwargs"]
profiles = ConstrainPaxisIp(
    eq=eq,
    paxis=float(pk["paxis"]),
    Ip=float(pk["Ip"]),
    fvac=float(dump["fvac"]),
    alpha_m=float(pk["alpha_m"]),
    alpha_n=float(pk["alpha_n"]),
)
eq.plasma_psi = np.asarray(dump["plasma_psi"], dtype=float)
GS = GSstaticsolver.NKGSsolver(eq)
GS.solve(eq=eq, profiles=profiles, constrain=None, target_relative_tolerance=1e-6, verbose=0)
lc = lcfs_arrays_from_eq(eq)
if lc is None:
    raise SystemExit("lcfs_extract_failed")
t0 = dump.get("t0")
pers = persist_lcfs_from_eq(HERE, eq, time_s=float(t0) if t0 is not None else None)
dump["lcfs_R"] = np.asarray(lc[0], dtype=float)
dump["lcfs_Z"] = np.asarray(lc[1], dtype=float)
try:
    _psi_total = eq.psi() if callable(getattr(eq, "psi", None)) else None
    if _psi_total is not None:
        dump["total_psi"] = np.asarray(_psi_total, dtype=float)
except Exception:
    pass
with open(HERE / "inverse_dump.pkl", "wb") as f:
    pickle.dump(dump, f)
print("ok", pers.get("n_points"), pers.get("paths"))
"""
    env = dict(os.environ)
    src_path = str((root / "src").resolve())
    prev = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src_path + ((os.pathsep + prev) if prev else "")
    try:
        r = subprocess.run(
            [str(py), "-c", script],
            capture_output=True,
            text=True,
            env=env,
            timeout=float(timeout_s),
        )
    except Exception as e:
        report["errors"].append(f"{type(e).__name__}:{e}")
        return report
    if r.returncode != 0:
        report["errors"].append(
            f"freegsnke_lcfs_recover_failed:rc={r.returncode}:{(r.stderr or r.stdout or '')[-500:]}"
        )
        return report
    report["ok"] = True
    report["stdout"] = (r.stdout or "")[-300:]
    return report
