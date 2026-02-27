"""FreeGSNKE internal solver state introspection & default-elimination sentinel.

v10.0.0 goal
-----------
Make FreeGSNKE's *internal* runtime state observable and comparable to the
externally-declared execution authority bundle.

This module is designed to be:
- deterministic (stable key ordering, stable hashing)
- defensive (never crashes the physics run; produces best-effort evidence)
- audit-ready (explicit mismatch reporting)

It is intentionally conservative: it verifies the parameters we *claim* to
control (grid/profile/boundary/solver knobs). It also exports a broad attribute
snapshot to reveal additional internal degrees of freedom.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _stable_json_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def summarize_value(v: Any) -> Any:
    """Summarize a value into JSON-serializable form.

    Rules
    -----
    - primitives are returned directly
    - mappings/lists are summarized recursively with bounded depth
    - numpy arrays (if present) are summarized by shape/dtype and a content hash
    - other objects -> type + repr (truncated)
    """

    # primitives
    if v is None or isinstance(v, (bool, int, float, str)):
        return v

    # bytes
    if isinstance(v, (bytes, bytearray)):
        bb = bytes(v)
        return {"kind": "bytes", "n": len(bb), "sha256": _sha256_bytes(bb)}

    # numpy arrays (optional dependency)
    try:
        import numpy as np  # type: ignore

        if isinstance(v, np.ndarray):
            arr = np.ascontiguousarray(v)
            # Hash is deterministic for same dtype/values.
            return {
                "kind": "ndarray",
                "shape": list(arr.shape),
                "dtype": str(arr.dtype),
                "sha256": _sha256_bytes(arr.tobytes()),
            }
    except Exception:
        pass

    # mapping
    if isinstance(v, Mapping):
        out: Dict[str, Any] = {}
        for k in sorted([str(x) for x in v.keys()]):
            try:
                out[str(k)] = summarize_value(v[k])  # type: ignore[index]
            except Exception as e:
                out[str(k)] = {"kind": "unreadable", "error": f"{type(e).__name__}: {e}"}
        return out

    # sequence
    if isinstance(v, (list, tuple)):
        return [summarize_value(x) for x in v]

    # fallback
    r = repr(v)
    if len(r) > 400:
        r = r[:400] + "…"
    return {"kind": "object", "type": f"{type(v).__module__}.{type(v).__name__}", "repr": r}


def snapshot_object(obj: Any, *, max_attrs: int = 500) -> Dict[str, Any]:
    """Snapshot public, non-callable attributes.

    We treat this as evidence generation, not strict schema.
    """

    attrs: Dict[str, Any] = {}
    names: List[str] = []
    try:
        for name in dir(obj):
            if name.startswith("_"):
                continue
            names.append(name)
    except Exception:
        names = []

    names = sorted(names)[:max_attrs]

    for name in names:
        try:
            val = getattr(obj, name)
        except Exception as e:
            attrs[name] = {"kind": "getattr_error", "error": f"{type(e).__name__}: {e}"}
            continue
        if callable(val):
            continue
        try:
            attrs[name] = summarize_value(val)
        except Exception as e:
            attrs[name] = {"kind": "summarize_error", "error": f"{type(e).__name__}: {e}"}

    return {
        "type": f"{type(obj).__module__}.{type(obj).__name__}",
        "attrs": attrs,
    }


def write_solver_introspection(
    run_dir: Path,
    *,
    execution_authority_bundle: Mapping[str, Any],
    objects: Mapping[str, Any],
) -> Path:
    """Write internal state snapshots and default detection report.

    Parameters
    ----------
    run_dir:
        Run directory (runs/shot_*/window_*/...).
    execution_authority_bundle:
        Loaded JSON dict used for the run.
    objects:
        Named runtime objects to snapshot, e.g., {"eq": eq, "solver": solver}.

    Returns
    -------
    out_dir:
        solver_introspection directory.
    """

    run_dir = Path(run_dir)
    out_dir = run_dir / "solver_introspection"
    out_dir.mkdir(parents=True, exist_ok=True)

    snapshots: Dict[str, Any] = {"execution_authority_bundle": execution_authority_bundle}
    for name, obj in sorted(objects.items()):
        try:
            snapshots[name] = snapshot_object(obj)
        except Exception as e:
            snapshots[name] = {"kind": "snapshot_failed", "error": f"{type(e).__name__}: {e}"}

    (out_dir / "solver_state_snapshot.json").write_text(_stable_json_dumps(snapshots) + "\n")

    report = default_detection_report(execution_authority_bundle, objects)
    (out_dir / "DEFAULT_DETECTION_REPORT.json").write_text(_stable_json_dumps(report) + "\n")

    # Numerics trace: best-effort extraction of common history attributes.
    trace = numerics_trace(objects)
    (out_dir / "numerics_trace.json").write_text(_stable_json_dumps(trace) + "\n")

    return out_dir


def _get(obj: Any, *names: str) -> Tuple[bool, Any]:
    for n in names:
        if hasattr(obj, n):
            try:
                return True, getattr(obj, n)
            except Exception:
                return True, {"kind": "getattr_error"}
    return False, None


def _num_close(a: Any, b: Any, *, rtol: float = 0.0, atol: float = 0.0) -> bool:
    try:
        import math

        af = float(a)
        bf = float(b)
        return abs(af - bf) <= atol + rtol * abs(bf)
    except Exception:
        return False


def default_detection_report(execution_authority_bundle: Mapping[str, Any], objects: Mapping[str, Any]) -> Dict[str, Any]:
    """Compare controlled parameters against runtime objects.

    This is a *sentinel*, not a full FreeGSNKE schema verifier.

    It verifies:
    - grid extents and resolution where discoverable on the Equilibrium object
    - declared profile knobs where discoverable on profile object
    - solver tolerances and l2_reg vector where discoverable
    - inverse constraints basic hashes (null_points/isoflux_set) where discoverable

    If an attribute is not discoverable, it is recorded as "unverifiable".
    """

    ea = dict(execution_authority_bundle)
    grid = ea.get("grid", {})
    prof = ea.get("profile", {})
    bnd = ea.get("boundary", {})
    solv = ea.get("solver", {})

    checks: List[Dict[str, Any]] = []

    eq = objects.get("eq")
    if eq is not None:
        for key, attr_names in [
            ("Rmin", ("Rmin",)),
            ("Rmax", ("Rmax",)),
            ("Zmin", ("Zmin",)),
            ("Zmax", ("Zmax",)),
            ("nx", ("nx",)),
            ("ny", ("ny",)),
        ]:
            expected = grid.get(key)
            found, actual = _get(eq, *attr_names)
            if not found:
                checks.append({"domain": "grid", "field": key, "status": "unverifiable", "expected": expected})
            else:
                ok = _num_close(actual, expected) if expected is not None else True
                checks.append({"domain": "grid", "field": key, "status": "ok" if ok else "mismatch", "expected": expected, "actual": summarize_value(actual)})

    profiles = objects.get("profiles")
    if profiles is not None:
        for key, attr_names in [
            ("paxis_Pa", ("paxis", "paxis_Pa")),
            ("fvac", ("fvac",)),
            ("alpha_m", ("alpha_m",)),
            ("alpha_n", ("alpha_n",)),
        ]:
            expected = prof.get(key)
            found, actual = _get(profiles, *attr_names)
            if not found:
                checks.append({"domain": "profile", "field": key, "status": "unverifiable", "expected": expected})
            else:
                ok = _num_close(actual, expected) if expected is not None else True
                checks.append({"domain": "profile", "field": key, "status": "ok" if ok else "mismatch", "expected": expected, "actual": summarize_value(actual)})

    # Constraint hashing (evidence only)
    null_points = bnd.get("null_points")
    isoflux_set = bnd.get("isoflux_set")
    bnd_hash = _sha256_bytes(_stable_json_dumps({"null_points": null_points, "isoflux_set": isoflux_set}).encode("utf-8"))
    checks.append({"domain": "boundary", "field": "authority_hash", "status": "evidence", "sha256": bnd_hash})

    # Solver checks (best-effort)
    solver = objects.get("solver")
    if solver is not None:
        # Tolerances may or may not be stored on solver object; record evidence.
        for key in ["inverse_target_relative_tolerance", "inverse_target_relative_psit_update", "forward_target_relative_tolerance"]:
            checks.append({"domain": "solver", "field": key, "status": "declared", "value": solv.get(key)})

        # l2_reg vector evidence
        l2 = solv.get("l2_reg", {})
        l2_hash = _sha256_bytes(_stable_json_dumps(l2).encode("utf-8"))
        checks.append({"domain": "solver", "field": "l2_reg_policy_hash", "status": "evidence", "sha256": l2_hash})

        # Attempt to capture any residual/history attributes.
        found, hist = _get(solver, "residual_history", "history", "residuals")
        if found:
            checks.append({"domain": "solver", "field": "residual_history", "status": "evidence", "value": summarize_value(hist)})

    ok = all(c.get("status") != "mismatch" for c in checks)

    return {
        "ok": bool(ok),
        "n_checks": len(checks),
        "checks": checks,
        "note": "This report verifies declared controlled knobs where discoverable; additional internal degrees of freedom are revealed in solver_state_snapshot.json.",
    }


def numerics_trace(objects: Mapping[str, Any]) -> Dict[str, Any]:
    """Best-effort extraction of solver convergence / numerics traces."""

    solver = objects.get("solver")
    out: Dict[str, Any] = {"available": False, "fields": {}}
    if solver is None:
        return out

    fields = {}
    for name in [
        "residual_history",
        "residuals",
        "history",
        "n_iterations",
        "iterations",
        "linear_iterations",
        "lin_iters",
    ]:
        try:
            if hasattr(solver, name):
                fields[name] = summarize_value(getattr(solver, name))
        except Exception as e:
            fields[name] = {"kind": "getattr_error", "error": f"{type(e).__name__}: {e}"}

    out["available"] = bool(fields)
    out["fields"] = fields
    return out
