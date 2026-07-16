from __future__ import annotations

import importlib.util
import json
import math
import pickle
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union


# -----------------------------
# Data model (internal authority)
# -----------------------------
@dataclass(frozen=True)
class FluxLoop:
    name: str
    r_m: float
    z_m: float
    # Optional metadata (NOT required for FreeGSNKE point-flux probes)
    turns: Optional[int] = None
    area_m2: Optional[float] = None
    psi_coupling_factor: Optional[float] = None


@dataclass(frozen=True)
class PickupCoil:
    name: str
    r_m: float
    z_m: float
    # FreeGSNKE pickups use a 3D position (R, phi, Z). We keep phi explicit.
    # Convention: degrees unless otherwise stated in metadata.
    phi_deg: float
    # Unit orientation vector components in (R, phi, Z) basis, matching FreeGSNKE expectation.
    n_r: float
    n_phi: float
    n_z: float
    # Optional metadata
    effective_area_m2: Optional[float] = None
    gain: Optional[float] = None
    orientation: Optional[str] = None  # e.g. PARALLEL, TOROIDAL, NORMAL


@dataclass(frozen=True)
class ProbeGeometry:
    flux_loops: List[FluxLoop]
    pickup_coils: List[PickupCoil]
    metadata: Dict[str, object]


def _finite(x: float) -> bool:
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def validate_geometry(geom: ProbeGeometry) -> Tuple[bool, List[str]]:
    """Internal validation.

    This validates deterministic completeness and numerical sanity.
    It does NOT claim physics correctness of metrology.
    """
    errs: List[str] = []

    if geom.flux_loops is None or geom.pickup_coils is None:
        errs.append("geometry lists must not be None")

    if len(geom.flux_loops) == 0:
        errs.append("no flux loops defined")

    if len(geom.pickup_coils) == 0:
        errs.append("no pickup coils defined")

    # Flux loops: minimal is (R,Z)
    for i, fl in enumerate(geom.flux_loops):
        if not fl.name:
            errs.append(f"flux_loops[{i}].name missing")
        if not _finite(fl.r_m) or not _finite(fl.z_m):
            errs.append(f"flux_loops[{i}] non-finite R/Z")
        if fl.turns is not None and (not isinstance(fl.turns, int) or fl.turns <= 0):
            errs.append(f"flux_loops[{i}].turns must be positive int if provided")
        if fl.area_m2 is not None and (not _finite(fl.area_m2) or fl.area_m2 <= 0.0):
            errs.append(f"flux_loops[{i}].area_m2 must be >0 if provided")

    # Pickup coils: require (R,phi,Z) and a unit-ish orientation vector
    for i, pc in enumerate(geom.pickup_coils):
        if not pc.name:
            errs.append(f"pickup_coils[{i}].name missing")
        if not (_finite(pc.r_m) and _finite(pc.phi_deg) and _finite(pc.z_m)):
            errs.append(f"pickup_coils[{i}] non-finite (R,phi,Z)")
        if not (_finite(pc.n_r) and _finite(pc.n_phi) and _finite(pc.n_z)):
            errs.append(f"pickup_coils[{i}] non-finite orientation vector components")
        n2 = pc.n_r * pc.n_r + pc.n_phi * pc.n_phi + pc.n_z * pc.n_z
        if not _finite(n2) or n2 <= 0.0:
            errs.append(f"pickup_coils[{i}] orientation vector has zero/invalid norm")
        # unit-ish tolerance: allow 1 +/- 5%
        if abs(math.sqrt(n2) - 1.0) > 0.05:
            errs.append(f"pickup_coils[{i}] orientation vector must be ~unit length (|n|-1 > 0.05)")
        if pc.effective_area_m2 is not None and (not _finite(pc.effective_area_m2) or pc.effective_area_m2 <= 0.0):
            errs.append(f"pickup_coils[{i}].effective_area_m2 must be >0 if provided")

    return (len(errs) == 0), errs


# --------------------------------
# FreeGSNKE compatibility interface
# --------------------------------
def to_freegsnke_magnetic_probes(geom: ProbeGeometry) -> Dict[str, object]:
    """Convert internal geometry to the minimal FreeGSNKE `magnetic_probes` dict.

    FreeGSNKE docs specify:
      magnetic_probes = {'flux_loops': [{'name', 'position'(R,Z)}...],
                         'pickups':    [{'name','position'(R,phi,Z),'orientation','orientation_vector'}...]}

    We follow that convention exactly. citeturn4view0
    """
    # Optional numpy acceleration; we avoid a hard dependency.
    try:
        import numpy as np  # type: ignore
    except Exception:
        np = None  # type: ignore

    flux_loops: List[Dict[str, object]] = []
    for fl in geom.flux_loops:
        pos = [float(fl.r_m), float(fl.z_m)]
        flux_loops.append(
            {
                "name": fl.name,
                "position": (np.array(pos) if np is not None else pos),
            }
        )

    pickups: List[Dict[str, object]] = []
    for pc in geom.pickup_coils:
        pos3 = [float(pc.r_m), float(pc.phi_deg), float(pc.z_m)]
        n3 = [float(pc.n_r), float(pc.n_phi), float(pc.n_z)]
        pickups.append(
            {
                "name": pc.name,
                "position": (np.array(pos3) if np is not None else pos3),
                "orientation": (pc.orientation or "UNSPECIFIED"),
                "orientation_vector": (np.array(n3) if np is not None else n3),
            }
        )

    return {"flux_loops": flux_loops, "pickups": pickups}


# -----------------
# IO: JSON / pickle
# -----------------
def write_geometry_json(path: Path, geom: ProbeGeometry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "flux_loops": [asdict(x) for x in geom.flux_loops],
        "pickup_coils": [asdict(x) for x in geom.pickup_coils],
        "metadata": geom.metadata,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def write_geometry_pickle(path: Path, geom: ProbeGeometry) -> None:
    """Write `magnetic_probes.pickle` in FreeGSNKE-compatible format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_freegsnke_magnetic_probes(geom)
    with open(path, "wb") as f:
        pickle.dump(payload, f)


def write_geometry_pickle_internal(path: Path, geom: ProbeGeometry) -> None:
    """Write a pickle of the internal dataclass for debugging/auditing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(geom, f)


# -----------------------
# Machine-dir source layer
# -----------------------
def _load_json_geometry(path: Path) -> ProbeGeometry:
    obj = json.loads(path.read_text())

    metadata = dict(obj.get("metadata", {}))
    fls: List[FluxLoop] = []
    for x in obj.get("flux_loops", []):
        fls.append(
            FluxLoop(
                name=str(x["name"]),
                r_m=float(x["r_m"]),
                z_m=float(x["z_m"]),
                turns=(int(x["turns"]) if x.get("turns") is not None else None),
                area_m2=(float(x["area_m2"]) if x.get("area_m2") is not None else None),
                psi_coupling_factor=(float(x["psi_coupling_factor"]) if x.get("psi_coupling_factor") is not None else None),
            )
        )

    pcs: List[PickupCoil] = []
    for x in obj.get("pickup_coils", []):
        pcs.append(
            PickupCoil(
                name=str(x["name"]),
                r_m=float(x["r_m"]),
                z_m=float(x["z_m"]),
                phi_deg=float(x["phi_deg"]),
                n_r=float(x["n_r"]),
                n_phi=float(x["n_phi"]),
                n_z=float(x["n_z"]),
                effective_area_m2=(float(x["effective_area_m2"]) if x.get("effective_area_m2") is not None else None),
                gain=(float(x["gain"]) if x.get("gain") is not None else None),
                orientation=(str(x["orientation"]) if x.get("orientation") is not None else None),
            )
        )

    return ProbeGeometry(flux_loops=fls, pickup_coils=pcs, metadata=metadata)


def _load_py_builder(path: Path) -> Optional[ProbeGeometry]:
    spec = importlib.util.spec_from_file_location("mast_freegsnke_machine", str(path))
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore

    # Supported entrypoints
    if hasattr(mod, "build_probe_geometry"):
        geom = mod.build_probe_geometry()
    elif hasattr(mod, "get_probe_geometry"):
        geom = mod.get_probe_geometry()
    else:
        return None

    # Allow returning already as ProbeGeometry or as dict matching JSON schema.
    if isinstance(geom, ProbeGeometry):
        return geom
    if isinstance(geom, dict):
        # interpret dict as JSON-schema-like
        tmp_path = Path(path.parent) / ".__tmp_probe_geometry__.json"
        tmp_path.write_text(json.dumps(geom))
        try:
            return _load_json_geometry(tmp_path)
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass
    return None


def _load_csv_table(path: Path) -> List[Dict[str, str]]:
    import csv

    with open(path, "r", newline="") as f:
        return list(csv.DictReader(f))


def _load_csv_geometry(machine_dir: Path) -> Optional[ProbeGeometry]:
    fl_path = machine_dir / "flux_loops.csv"
    pc_path = machine_dir / "pickup_coils.csv"
    if not fl_path.exists() or not pc_path.exists():
        return None

    fl_rows = _load_csv_table(fl_path)
    pc_rows = _load_csv_table(pc_path)

    fls: List[FluxLoop] = []
    for r in fl_rows:
        fls.append(
            FluxLoop(
                name=str(r["name"]),
                r_m=float(r["r_m"]),
                z_m=float(r["z_m"]),
                turns=(int(r["turns"]) if r.get("turns") not in (None, "", "null") else None),
                area_m2=(float(r["area_m2"]) if r.get("area_m2") not in (None, "", "null") else None),
                psi_coupling_factor=(float(r["psi_coupling_factor"]) if r.get("psi_coupling_factor") not in (None, "", "null") else None),
            )
        )

    pcs: List[PickupCoil] = []
    for r in pc_rows:
        pcs.append(
            PickupCoil(
                name=str(r["name"]),
                r_m=float(r["r_m"]),
                z_m=float(r["z_m"]),
                phi_deg=float(r["phi_deg"]),
                n_r=float(r["n_r"]),
                n_phi=float(r["n_phi"]),
                n_z=float(r["n_z"]),
                effective_area_m2=(float(r["effective_area_m2"]) if r.get("effective_area_m2") not in (None, "", "null") else None),
                gain=(float(r["gain"]) if r.get("gain") not in (None, "", "null") else None),
                orientation=(str(r["orientation"]) if r.get("orientation") not in (None, "", "null") else None),
            )
        )

    meta: Dict[str, object] = {
        "source": "csv",
        "phi_unit": "deg",
    }
    return ProbeGeometry(flux_loops=fls, pickup_coils=pcs, metadata=meta)


def build_geometry_from_machine_dir(machine_dir: Path) -> Tuple[Optional[ProbeGeometry], Dict[str, object]]:
    """Resolve probe geometry from a machine directory.

    Precedence:
      1) probe_geometry.json
      2) probe_geometry.py or machine.py providing builder function
      3) flux_loops.csv + pickup_coils.csv
    """
    report: Dict[str, object] = {
        "machine_dir": str(machine_dir),
        "resolved": False,
        "source": None,
        "errors": [],
        "notes": [],
    }
    machine_dir = Path(machine_dir)

    # 1) JSON
    json_path = machine_dir / "probe_geometry.json"
    if json_path.exists():
        try:
            raw_txt = json_path.read_text(encoding="utf-8")
            if "TEMPLATE" in raw_txt.upper() or "CHANGE_ME" in raw_txt.upper():
                report["errors"] = ["template_or_CHANGE_ME_probe_geometry_refused"]
                report["notes"].append("Refuse template probe geometry (do not invent metrology)")
                return None, report
            geom = _load_json_geometry(json_path)
            ok, errs = validate_geometry(geom)
            if not ok:
                report["errors"] = errs
                report["notes"].append("probe_geometry.json present but failed validation")
                return None, report
            report["resolved"] = True
            report["source"] = "probe_geometry.json"
            return geom, report
        except Exception as e:
            report["errors"].append(f"failed to load probe_geometry.json: {e!r}")
            return None, report

    # 2) Python module builder
    for cand in ["probe_geometry.py", "machine.py", "machine_stub_freegsnke.py"]:
        p = machine_dir / cand
        if p.exists():
            try:
                geom = _load_py_builder(p)
                if geom is None:
                    continue
                ok, errs = validate_geometry(geom)
                if not ok:
                    report["errors"] = errs
                    report["notes"].append(f"{cand} builder returned geometry but failed validation")
                    return None, report
                report["resolved"] = True
                report["source"] = f"python:{cand}"
                return geom, report
            except Exception as e:
                report["errors"].append(f"failed to load {cand}: {e!r}")
                return None, report

    # 3) CSV
    try:
        geom = _load_csv_geometry(machine_dir)
        if geom is not None:
            ok, errs = validate_geometry(geom)
            if not ok:
                report["errors"] = errs
                report["notes"].append("CSV geometry present but failed validation")
                return None, report
            report["resolved"] = True
            report["source"] = "csv"
            return geom, report
    except Exception as e:
        report["errors"].append(f"failed to load CSV geometry: {e!r}")
        return None, report

    report["errors"].append(
        "No probe geometry found. Provide one of: probe_geometry.json, a Python builder (probe_geometry.py/machine.py), "
        "or flux_loops.csv + pickup_coils.csv."
    )
    return None, report


# -------------------
# Templates + smoke QC
# -------------------
def write_geometry_templates(machine_dir: Path) -> Dict[str, str]:
    """Write template files to help users populate authoritative geometry."""
    machine_dir = Path(machine_dir)
    machine_dir.mkdir(parents=True, exist_ok=True)

    # JSON template
    template = {
        "metadata": {
            "phi_unit": "deg",
            "note": "Fill with authoritative MAST metrology. Do NOT guess.",
        },
        "flux_loops": [
            {"name": "fl_001", "r_m": 0.9, "z_m": 1.35, "turns": None, "area_m2": None, "psi_coupling_factor": None},
        ],
        "pickup_coils": [
            {
                "name": "b_001",
                "r_m": 0.28,
                "phi_deg": 300.0,
                "z_m": 1.26,
                "n_r": 0.0,
                "n_phi": 0.0,
                "n_z": 1.0,
                "effective_area_m2": None,
                "gain": None,
                "orientation": "PARALLEL",
            },
        ],
    }
    (machine_dir / "probe_geometry.template.json").write_text(json.dumps(template, indent=2, sort_keys=True))

    # CSV templates
    import csv

    fl_fields = ["name", "r_m", "z_m", "turns", "area_m2", "psi_coupling_factor"]
    pc_fields = ["name", "r_m", "phi_deg", "z_m", "n_r", "n_phi", "n_z", "effective_area_m2", "gain", "orientation"]

    with open(machine_dir / "flux_loops.template.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fl_fields)
        w.writeheader()
        w.writerow({"name": "fl_001", "r_m": "0.9", "z_m": "1.35", "turns": "", "area_m2": "", "psi_coupling_factor": ""})

    with open(machine_dir / "pickup_coils.template.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=pc_fields)
        w.writeheader()
        w.writerow(
            {
                "name": "b_001",
                "r_m": "0.28",
                "phi_deg": "300.0",
                "z_m": "1.26",
                "n_r": "0.0",
                "n_phi": "0.0",
                "n_z": "1.0",
                "effective_area_m2": "",
                "gain": "",
                "orientation": "PARALLEL",
            }
        )

    return {
        "probe_geometry.template.json": str(machine_dir / "probe_geometry.template.json"),
        "flux_loops.template.csv": str(machine_dir / "flux_loops.template.csv"),
        "pickup_coils.template.csv": str(machine_dir / "pickup_coils.template.csv"),
    }


def smoke_test_geometry(geom: ProbeGeometry) -> Tuple[bool, Dict[str, object]]:
    """Smoke test: finite values, unit normals, and FreeGSNKE dict conversion."""
    ok, errs = validate_geometry(geom)
    report: Dict[str, object] = {
        "ok": ok,
        "errors": errs,
        "n_flux_loops": len(geom.flux_loops),
        "n_pickup_coils": len(geom.pickup_coils),
    }
    if not ok:
        return False, report

    # Convert to FreeGSNKE dict and perform shallow structural checks
    mp = to_freegsnke_magnetic_probes(geom)
    if "flux_loops" not in mp or "pickups" not in mp:
        return False, {**report, "ok": False, "errors": ["missing keys in freegsnke dict"]}
    if len(mp["flux_loops"]) != len(geom.flux_loops):
        return False, {**report, "ok": False, "errors": ["flux loop count mismatch after conversion"]}
    if len(mp["pickups"]) != len(geom.pickup_coils):
        return False, {**report, "ok": False, "errors": ["pickup count mismatch after conversion"]}

    return True, report
