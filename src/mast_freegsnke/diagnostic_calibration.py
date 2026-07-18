"""Optional diagnostic calibration authority (mirnov / saddle / omaha).

Fail-closed, never invents V→T / V→Wb factors or probe geometry.

When ``diagnostic_calibration_path`` points at a valid authority with non-empty
``channels``, calibrated traces are written to production inputs
(``inputs/mirnov.csv``, ``inputs/saddle.csv``, ``inputs/omaha.csv``) in
``units_out``. Uncalibrated channels stay audit-only under
``inputs/audit_other_timebase/``.

Unit-metadata contradictions (e.g. units='T' vs label='Tesla/sec') may be
resolved ONLY via explicit ``unit_resolution`` entries — never by silent
heuristics.

FreeGSNKE synthesizer / identity contracts are emitted only when a channel
entry sets ``synthesize: true``, ``units_out`` is a synthesizable unit (T or
Wb), and ``syn_probe`` is declared. Saddle has no FreeGSNKE path-integral
synthesizer; OMAHA has no R/Z in machine_authority — both remain
extract+calibrate only unless geometry authority is later extended.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .util import ensure_dir, sha256_file, write_json


class CalibrationError(ValueError):
    """Raised when diagnostic calibration authority is invalid or inconsistent."""


_ALLOWED_STATUS = {
    "awaiting_authority",
    "partial",
    "active",
}
_SYNTHESIZABLE_UNITS = {"T", "Wb"}
_REQUIRED_CHANNEL_KEYS = (
    "exp_column",
    "units_in",
    "units_out",
    "scale",
    "sign",
    "source",
)


@dataclass(frozen=True)
class ChannelCalibration:
    """One explicit per-channel calibration entry."""

    key: str
    family: str
    source_variable: str
    exp_column: str
    production_column: str
    units_in: str
    units_out: str
    scale: float
    sign: int
    source: str
    offset: float = 0.0
    notes: Optional[str] = None
    synthesize: bool = False
    syn_probe: Optional[str] = None
    syn_csv: str = "synthetic/synthetic_pickups.csv"
    dtype: str = "pickup"


@dataclass(frozen=True)
class UnitResolution:
    """Explicit resolution of units-vs-label contradiction for a source variable."""

    source_variable: str
    resolved_units: str
    source: str
    notes: Optional[str] = None


@dataclass(frozen=True)
class DiagnosticCalibration:
    """Loaded diagnostic calibration authority."""

    version: str
    status: str
    channels: Dict[str, ChannelCalibration]
    unit_resolution: Dict[str, UnitResolution]
    calibratable_families: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None

    @property
    def n_calibrated(self) -> int:
        return len(self.channels)

    @property
    def n_synthesizable(self) -> int:
        return sum(1 for c in self.channels.values() if c.synthesize)


def _require_str(obj: Dict[str, Any], key: str, ctx: str) -> str:
    val = obj.get(key)
    if not isinstance(val, str) or not val.strip():
        raise CalibrationError(f"{ctx}: missing/empty string '{key}'")
    return val.strip()


def load_diagnostic_calibration(path: Path) -> DiagnosticCalibration:
    """Load and validate diagnostic calibration JSON (fail-closed)."""
    if not path.exists():
        raise CalibrationError(f"diagnostic_calibration_path not found: {path}")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise CalibrationError(f"diagnostic_calibration JSON parse error: {e}") from e
    if not isinstance(obj, dict):
        raise CalibrationError("diagnostic_calibration JSON root must be an object")

    version = str(obj.get("version", "1.0"))
    status = str(obj.get("status", "awaiting_authority")).strip()
    if status not in _ALLOWED_STATUS:
        raise CalibrationError(
            f"status must be one of {sorted(_ALLOWED_STATUS)} (got {status!r}); "
            "example templates must not be used as production authority"
        )

    families = obj.get("calibratable_families", {}) or {}
    if families is not None and not isinstance(families, dict):
        raise CalibrationError("'calibratable_families' must be an object")

    unit_res_raw = obj.get("unit_resolution", {}) or {}
    if not isinstance(unit_res_raw, dict):
        raise CalibrationError("'unit_resolution' must be an object")
    unit_resolution: Dict[str, UnitResolution] = {}
    for var, spec in unit_res_raw.items():
        if not isinstance(spec, dict):
            raise CalibrationError(f"unit_resolution.{var}: must be an object")
        unit_resolution[str(var)] = UnitResolution(
            source_variable=str(var),
            resolved_units=_require_str(spec, "resolved_units", f"unit_resolution.{var}"),
            source=_require_str(spec, "source", f"unit_resolution.{var}"),
            notes=(str(spec["notes"]) if spec.get("notes") is not None else None),
        )

    channels_raw = obj.get("channels", {}) or {}
    if not isinstance(channels_raw, dict):
        raise CalibrationError("'channels' must be an object")

    channels: Dict[str, ChannelCalibration] = {}
    for key, spec in channels_raw.items():
        ctx = f"channels.{key}"
        if not isinstance(spec, dict):
            raise CalibrationError(f"{ctx}: must be an object")
        for req in _REQUIRED_CHANNEL_KEYS:
            if req not in spec:
                raise CalibrationError(f"{ctx}: missing required key '{req}'")
        family = str(spec.get("family") or _family_from_variable(str(spec.get("source_variable", ""))))
        if family not in {"mirnov", "saddle", "omaha", "pickup"}:
            raise CalibrationError(f"{ctx}: family must be mirnov|saddle|omaha|pickup (got {family!r})")
        source_variable = _require_str(spec, "source_variable", ctx) if "source_variable" in spec else None
        if source_variable is None:
            raise CalibrationError(f"{ctx}: missing required key 'source_variable'")
        exp_column = _require_str(spec, "exp_column", ctx)
        production_column = str(spec.get("production_column") or key).strip()
        if not production_column:
            raise CalibrationError(f"{ctx}: production_column empty")
        units_in = _require_str(spec, "units_in", ctx)
        units_out = _require_str(spec, "units_out", ctx)
        try:
            scale = float(spec["scale"])
        except (TypeError, ValueError) as e:
            raise CalibrationError(f"{ctx}: scale must be numeric") from e
        if not (scale == scale) or scale == 0.0:  # NaN or zero
            raise CalibrationError(f"{ctx}: scale must be finite and non-zero")
        sign = spec.get("sign", 1)
        try:
            sign_i = int(sign)
        except (TypeError, ValueError) as e:
            raise CalibrationError(f"{ctx}: sign must be +1 or -1") from e
        if sign_i not in (-1, 1):
            raise CalibrationError(f"{ctx}: sign must be +1 or -1")
        try:
            offset = float(spec.get("offset", 0.0))
        except (TypeError, ValueError) as e:
            raise CalibrationError(f"{ctx}: offset must be numeric") from e
        source = _require_str(spec, "source", ctx)
        synthesize = bool(spec.get("synthesize", False))
        syn_probe = (str(spec["syn_probe"]).strip() if spec.get("syn_probe") is not None else None)
        syn_csv = str(spec.get("syn_csv") or "synthetic/synthetic_pickups.csv")
        dtype = str(spec.get("dtype") or "pickup")
        if synthesize:
            if units_out not in _SYNTHESIZABLE_UNITS:
                raise CalibrationError(
                    f"{ctx}: synthesize=true requires units_out in {sorted(_SYNTHESIZABLE_UNITS)} "
                    f"(got {units_out!r})"
                )
            if not syn_probe:
                raise CalibrationError(f"{ctx}: synthesize=true requires syn_probe (geometry probe name)")
            if family == "saddle":
                raise CalibrationError(
                    f"{ctx}: saddle has no FreeGSNKE synthesizer; set synthesize=false "
                    "(extract+calibrate / future contracts only)"
                )
            if family == "omaha":
                raise CalibrationError(
                    f"{ctx}: omaha has no R/Z in machine_authority; cannot synthesize "
                    "without inventing metrology (set synthesize=false)"
                )

        channels[str(key)] = ChannelCalibration(
            key=str(key),
            family=family,
            source_variable=source_variable,
            exp_column=exp_column,
            production_column=production_column,
            units_in=units_in,
            units_out=units_out,
            scale=scale,
            sign=sign_i,
            source=source,
            offset=offset,
            notes=(str(spec["notes"]) if spec.get("notes") is not None else None),
            synthesize=synthesize,
            syn_probe=syn_probe,
            syn_csv=syn_csv,
            dtype=dtype,
        )

    # Status consistency: empty channels => awaiting; non-empty should not claim awaiting
    if not channels and status == "active":
        raise CalibrationError("status='active' requires non-empty channels")
    if channels and status == "awaiting_authority":
        raise CalibrationError(
            "status='awaiting_authority' requires empty channels; "
            "use 'partial' or 'active' when channels are populated"
        )

    return DiagnosticCalibration(
        version=version,
        status=status,
        channels=channels,
        unit_resolution=unit_resolution,
        calibratable_families=dict(families),
        notes=(str(obj["notes"]) if obj.get("notes") is not None else None),
        raw=obj,
        path=path.resolve(),
    )


def _family_from_variable(var: str) -> str:
    v = var.lower()
    if "omaha" in v:
        return "omaha"
    if "saddle" in v:
        return "saddle"
    if "omv" in v or "mirnov" in v or "_cc_field" in v or "_cc_voltage" in v:
        return "mirnov"
    return "pickup"


def validate_diagnostic_calibration(cal: DiagnosticCalibration) -> Dict[str, Any]:
    """Return a validation report (ok/errors). load_* already fail-closed; this is for doctor."""
    report: Dict[str, Any] = {
        "ok": True,
        "errors": [],
        "n_calibrated": cal.n_calibrated,
        "n_synthesizable": cal.n_synthesizable,
        "status": cal.status,
    }
    # load already validated; re-check synthesizer gates for report completeness
    for ch in cal.channels.values():
        if ch.synthesize and ch.family in {"saddle", "omaha"}:
            report["ok"] = False
            report["errors"].append(f"{ch.key}: synthesize not allowed for family={ch.family}")
    return report


def apply_scale(y, *, scale: float, sign: int, offset: float = 0.0):
    """Deterministic calibration: sign * scale * y + offset."""
    import numpy as np

    arr = np.asarray(y, dtype=float)
    return (float(sign) * float(scale) * arr) + float(offset)


def resolved_units_for_variable(cal: DiagnosticCalibration, source_variable: str, attrs_units: Optional[str]) -> str:
    """Return authoritative units for a source variable (unit_resolution wins)."""
    if source_variable in cal.unit_resolution:
        return cal.unit_resolution[source_variable].resolved_units
    if attrs_units is None:
        raise CalibrationError(
            f"no units for {source_variable!r} and no unit_resolution entry; "
            "cannot apply calibration without explicit units"
        )
    return str(attrs_units)


def snapshot_diagnostic_calibration(cal: DiagnosticCalibration, run_dir: Path) -> Dict[str, Any]:
    """Copy + hash calibration authority into run_dir/contracts/."""
    out_dir = ensure_dir(Path(run_dir) / "contracts")
    snap_path = out_dir / "diagnostic_calibration.snapshot.json"
    payload = dict(cal.raw) if cal.raw else {
        "version": cal.version,
        "status": cal.status,
        "channels": {},
        "unit_resolution": {},
        "calibratable_families": cal.calibratable_families,
        "notes": cal.notes,
    }
    write_json(snap_path, payload)
    digest = sha256_file(snap_path)
    report = {
        "path": str(snap_path),
        "sha256": digest,
        "status": cal.status,
        "n_calibrated": cal.n_calibrated,
        "n_synthesizable": cal.n_synthesizable,
        "source_path": str(cal.path) if cal.path else None,
    }
    write_json(out_dir / "diagnostic_calibration.snapshot_report.json", report)
    return report


def apply_diagnostic_calibration(
    inputs_dir: Path,
    cal: DiagnosticCalibration,
    *,
    audit_subdir: str = "audit_other_timebase",
) -> Dict[str, Any]:
    """Apply calibration to audit CSVs → production family CSVs.

    Uncalibrated channels remain audit-only. Missing audit CSV / column is a
    soft skip recorded in the report (shot may not carry every family);
    schema-invalid calibration already failed at load time.
    """
    import pandas as pd

    report: Dict[str, Any] = {
        "ok": True,
        "errors": [],
        "applied": [],
        "skipped": [],
        "production_files": {},
        "status": cal.status,
        "n_calibrated": cal.n_calibrated,
    }
    if not cal.channels:
        report["note"] = "channels empty; mirnov/saddle/omaha remain audit-only"
        write_json(Path(inputs_dir) / "diagnostic_calibration_apply_report.json", report)
        return report

    audit_dir = Path(inputs_dir) / audit_subdir
    # family -> {time: Series, columns: {prod_col: values}}
    family_data: Dict[str, Dict[str, Any]] = {}

    for key, ch in cal.channels.items():
        csv_path = audit_dir / f"{ch.source_variable}.csv"
        if not csv_path.exists():
            report["skipped"].append(
                {"key": key, "reason": f"audit_csv_missing:{csv_path.name}"}
            )
            continue
        df = pd.read_csv(csv_path)
        if "time" not in df.columns:
            report["ok"] = False
            report["errors"].append(f"{key}: audit CSV missing 'time' column: {csv_path}")
            continue
        if ch.exp_column not in df.columns:
            report["skipped"].append(
                {
                    "key": key,
                    "reason": f"exp_column_missing:{ch.exp_column}",
                    "available": [c for c in df.columns if c != "time"][:40],
                }
            )
            continue

        # Units gate: channel units_in must match resolved units for the variable
        # (from unit_resolution or extract_meta if present).
        meta_units = _units_from_extract_meta(inputs_dir, ch.source_variable)
        try:
            authoritative = resolved_units_for_variable(cal, ch.source_variable, meta_units)
        except CalibrationError as e:
            report["ok"] = False
            report["errors"].append(f"{key}: {e}")
            continue
        if ch.units_in != authoritative:
            # Allow explicit unit_resolution to rename; channel must declare the resolved units_in
            report["ok"] = False
            report["errors"].append(
                f"{key}: units_in={ch.units_in!r} does not match authoritative units "
                f"{authoritative!r} for {ch.source_variable} "
                f"(add unit_resolution or fix units_in)"
            )
            continue

        y_cal = apply_scale(df[ch.exp_column].to_numpy(), scale=ch.scale, sign=ch.sign, offset=ch.offset)
        bucket = family_data.setdefault(
            ch.family,
            {"time": df["time"].to_numpy(), "columns": {}, "units_out": {}, "source_keys": {}},
        )
        # Native timebase must be consistent within a family production CSV
        import numpy as np

        if bucket["time"].shape != y_cal.shape and len(bucket["columns"]) == 0:
            bucket["time"] = df["time"].to_numpy()
        if not np.array_equal(bucket["time"], df["time"].to_numpy()):
            report["ok"] = False
            report["errors"].append(
                f"{key}: native timebase mismatch within family={ch.family} "
                f"(refusing to merge heterogeneous time axes into one CSV)"
            )
            continue
        if ch.production_column in bucket["columns"]:
            report["ok"] = False
            report["errors"].append(
                f"{key}: duplicate production_column {ch.production_column!r} in family={ch.family}"
            )
            continue
        bucket["columns"][ch.production_column] = y_cal
        bucket["units_out"][ch.production_column] = ch.units_out
        bucket["source_keys"][ch.production_column] = key
        report["applied"].append(
            {
                "key": key,
                "family": ch.family,
                "exp_column": ch.exp_column,
                "production_column": ch.production_column,
                "units_in": ch.units_in,
                "units_out": ch.units_out,
                "scale": ch.scale,
                "sign": ch.sign,
                "offset": ch.offset,
                "synthesize": ch.synthesize,
                "syn_probe": ch.syn_probe,
            }
        )

    for family, bucket in sorted(family_data.items()):
        if not bucket["columns"]:
            continue
        out_name = f"{family}.csv"
        out_path = Path(inputs_dir) / out_name
        data = {"time": bucket["time"]}
        for col in sorted(bucket["columns"].keys()):
            data[col] = bucket["columns"][col]
        pd.DataFrame(data).to_csv(out_path, index=False, float_format="%.8g")
        report["production_files"][family] = {
            "csv": f"inputs/{out_name}",
            "n_channels": len(bucket["columns"]),
            "channels": sorted(bucket["columns"].keys()),
            "units_out": bucket["units_out"],
        }

    write_json(Path(inputs_dir) / "diagnostic_calibration_apply_report.json", report)
    return report


def _units_from_extract_meta(inputs_dir: Path, source_variable: str) -> Optional[str]:
    meta_path = Path(inputs_dir) / "extract_meta.json"
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    audit = (
        (meta.get("probe_families") or {}).get("audit_other_timebase")
        or meta.get("audit_other_timebase")
        or {}
    )
    var = (audit.get("variables") or {}).get(source_variable) or {}
    units = var.get("units")
    return str(units) if units is not None else None


def contracts_from_calibration(cal: DiagnosticCalibration) -> List[Dict[str, Any]]:
    """Build identity contract dicts for synthesizable calibrated channels only.

    Prefer omit until authority present: returns [] when nothing is synthesizable.
    Paths are run-relative (resolved later by load_contracts(..., base_dir=run_dir)).
    """
    out: List[Dict[str, Any]] = []
    for ch in sorted(cal.channels.values(), key=lambda c: c.key):
        if not ch.synthesize or not ch.syn_probe:
            continue
        family_csv = f"inputs/{ch.family}.csv"
        out.append(
            {
                "name": ch.syn_probe,
                "dtype": ch.dtype,
                "units": ch.units_out,
                "notes": (
                    f"Calibration-authority contract ({ch.key}): "
                    f"{ch.source_variable}:{ch.exp_column} -> {ch.production_column} "
                    f"({ch.units_in}->{ch.units_out}, scale={ch.scale}, sign={ch.sign}); "
                    f"syn={ch.syn_probe}. source={ch.source}"
                    + (f"; {ch.notes}" if ch.notes else "")
                ),
                "exp": {
                    "csv": family_csv,
                    "time_col": "time",
                    "value_col": ch.production_column,
                    "scale": 1.0,
                    "sign": 1.0,
                },
                "syn": {
                    "csv": ch.syn_csv,
                    "time_col": "time",
                    "value_col": ch.syn_probe,
                    "scale": 1.0,
                    "sign": 1.0,
                },
            }
        )
    return out


def merge_calibration_contracts(
    base_contracts_path: Path,
    cal: DiagnosticCalibration,
    *,
    out_path: Path,
) -> Dict[str, Any]:
    """Write a merged contracts JSON (base + synthesizable calibration contracts)."""
    base = json.loads(base_contracts_path.read_text(encoding="utf-8"))
    if not isinstance(base, dict):
        raise CalibrationError("base contracts root must be an object")
    diags = list(base.get("diagnostics") or [])
    if not isinstance(diags, list):
        raise CalibrationError("base contracts 'diagnostics' must be a list")
    existing = {str(d.get("name")) for d in diags if isinstance(d, dict)}
    added: List[str] = []
    skipped_dup: List[str] = []
    for c in contracts_from_calibration(cal):
        name = str(c["name"])
        if name in existing:
            skipped_dup.append(name)
            continue
        diags.append(c)
        existing.add(name)
        added.append(name)
    merged = dict(base)
    merged["diagnostics"] = diags
    notes_extra = (
        f" Merged {len(added)} synthesizable calibration contracts "
        f"(diagnostic_calibration status={cal.status})."
    )
    merged["notes"] = (str(base.get("notes") or "") + notes_extra).strip()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"ok": True, "added": added, "skipped_duplicate": skipped_dup, "path": str(out_path)}


def calibration_status_line(
    *,
    path: Optional[str],
    cal: Optional[DiagnosticCalibration] = None,
    apply_report: Optional[Dict[str, Any]] = None,
) -> str:
    """One clear doctor / interactive banner line for mirnov/saddle/omaha."""
    if not path:
        return (
            "[INFO] mirnov/saddle/omaha: awaiting diagnostic_calibration_path "
            "(set configs/diagnostic_calibration.json or point diagnostic_calibration_path; "
            "never invents V->T factors)"
        )
    if cal is None:
        return (
            f"[INFO] mirnov/saddle/omaha: diagnostic_calibration_path={path} "
            "(not loaded yet; doctor validates on demand)"
        )
    if cal.n_calibrated == 0:
        return (
            "[INFO] mirnov/saddle/omaha: awaiting diagnostic_calibration channels "
            f"(status={cal.status}; populate channels in {path} with explicit "
            "scale/sign/source -- never invent V->T)"
        )
    n_applied = len((apply_report or {}).get("applied") or [])
    n_syn = cal.n_synthesizable
    return (
        f"[OK] mirnov/saddle/omaha: {cal.n_calibrated} channels in authority "
        f"({n_applied} applied this shot; {n_syn} synthesizable & contractable; "
        f"status={cal.status})"
    )


def empty_awaiting_authority_document() -> Dict[str, Any]:
    """Shipped empty authority document (no fabricated scales)."""
    return {
        "version": "1.0",
        "status": "awaiting_authority",
        "notes": (
            "Optional diagnostic calibration authority (v10.6.0). "
            "channels is empty by default — mirnov/saddle/omaha stay audit-only under "
            "inputs/audit_other_timebase/ until an explicit per-channel entry is provided. "
            "NEVER invent V→T / V→Wb numbers. Each channel entry must include "
            "exp_column, source_variable, units_in, units_out, scale, sign, source, and notes; "
            "optional offset, production_column, synthesize, syn_probe. "
            "unit_resolution resolves units-vs-label contradictions only via explicit declaration. "
            "Synthesize=true is allowed only for mirnov/pickup point probes with units_out T|Wb "
            "and a geometry syn_probe (FreeGSNKE calculate_pickup_value). "
            "Saddle: no FreeGSNKE synthesizer (28-point polylines) — calibrate for audit/future only. "
            "OMAHA: no R/Z in machine_authority — calibrate experimental only until geometry is imported from FAIR-MAST."
        ),
        "calibratable_families": {
            "mirnov": {
                "source_variables": [
                    "b_field_pol_probe_omv_voltage",
                    "b_field_pol_probe_cc_field",
                    "b_field_tor_probe_cc_field",
                ],
                "production_csv": "inputs/mirnov.csv",
                "freegsnke_synthesizer": "point_pickup_if_calibrated_to_T_and_geometry_syn_probe",
                "geometry_notes": (
                    "OMV_* and CC_MV_* point probes exist in machine_authority/probe_geometry.json; "
                    "OMV voltage channels need V→T; CC_*_field has units='T' vs label='Tesla/sec' "
                    "(requires unit_resolution; equilibrium B·n synth is only honest if resolved_units=T "
                    "and the signal is truly DC B, which Level-2 evidence does not support for CC mirnov)."
                ),
                "awaiting": "explicit per-channel scale/sign/source (and unit_resolution where contradictory)",
            },
            "saddle": {
                "source_variables": [
                    "b_field_tor_probe_saddle_voltage",
                    "b_field_tor_probe_saddle_field",
                ],
                "production_csv": "inputs/saddle.csv",
                "freegsnke_synthesizer": None,
                "awaiting": (
                    "explicit calibration; no FreeGSNKE saddle surface-flux synthesizer "
                    "(path geometry is 28-point polylines — do not invent equivalent-point model)"
                ),
            },
            "omaha": {
                "source_variables": [
                    "b_field_tor_probe_omaha_voltage",
                ],
                "production_csv": "inputs/omaha.csv",
                "freegsnke_synthesizer": None,
                "awaiting": (
                    "explicit V→T calibration AND R/Z geometry authority "
                    "(fairmast_authority does not import omaha r/z; Level-2 has no omaha geometry family wired)"
                ),
            },
        },
        "unit_resolution": {},
        "channels": {},
    }
