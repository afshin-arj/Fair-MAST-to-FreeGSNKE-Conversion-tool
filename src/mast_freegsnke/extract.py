from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any
import importlib.util


def _require(pkg: str):
    if importlib.util.find_spec(pkg) is None:
        raise RuntimeError(f"Missing optional dependency '{pkg}'. Install with: pip install -e '.[zarr]'")


@dataclass
class Extractor:
    formed_plasma_frac: float = 0.80

    def extract(self, shot_cache_dir: Path, out_inputs_dir: Path) -> Dict[str, Any]:
        _require("numpy"); _require("pandas"); _require("xarray")
        import numpy as np
        import pandas as pd
        import xarray as xr

        out_inputs_dir.mkdir(parents=True, exist_ok=True)

        pf_store = shot_cache_dir / "pf_active.zarr"
        mag_store = shot_cache_dir / "magnetics.zarr"
        if not pf_store.exists():
            raise FileNotFoundError(f"Missing {pf_store}")
        if not mag_store.exists():
            raise FileNotFoundError(f"Missing {mag_store}")

        ds_pf = xr.open_zarr(pf_store, consolidated=False)
        ds_mag = xr.open_zarr(mag_store, consolidated=False)

        def find_time_coord(ds):
            for c in ["time", "t", "Time"]:
                if c in ds.coords:
                    return c
            for k, v in ds.coords.items():
                if getattr(v, "ndim", 0) == 1:
                    return k
            raise KeyError("Could not identify time coordinate")

        t_pf = find_time_coord(ds_pf)
        t_mag = find_time_coord(ds_mag)

        ip_var = None
        for k in ds_mag.data_vars:
            kl = k.lower()
            if kl in ("ip", "plasma_current", "i_p"):
                ip_var = k
                break
        if ip_var is None:
            # fallback loose match
            for k in ds_mag.data_vars:
                kl = k.lower()
                if "plasma" in kl and "current" in kl:
                    ip_var = k
                    break
        if ip_var is None:
            raise KeyError("Could not find Ip variable in magnetics.zarr. Adjust extractor mapping.")

        t = ds_mag[t_mag].values.astype(float)
        ip = ds_mag[ip_var].values.astype(float)

        mask_pos = ip > 0
        t2 = t[mask_pos]; ip2 = ip[mask_pos]
        if t2.size < 5:
            raise RuntimeError("Not enough positive-Ip samples to choose formed plasma time.")
        ip_max = float(ip2.max())
        mask_flat = ip2 >= self.formed_plasma_frac * ip_max
        if not mask_flat.any():
            raise RuntimeError("No samples satisfy formed_plasma_frac threshold; lower formed_plasma_frac.")
        t_sel = t2[mask_flat]; ip_sel = ip2[mask_flat]
        dip = np.gradient(ip_sel, t_sel)
        idx = int(np.argmin(np.abs(dip)))
        t0 = float(t_sel[idx]); ip0 = float(ip_sel[idx])

        pd.DataFrame({"time": t, "ip": ip}).to_csv(out_inputs_dir/"ip.csv", index=False)

        # PF currents: prefer coil_current (channel, time) with current_channel labels.
        pf_df = pd.DataFrame({"time": ds_pf[t_pf].values.astype(float)})
        exported_pf = []
        if "coil_current" in ds_pf and "current_channel" in ds_pf.coords:
            channels = [str(x) for x in ds_pf["current_channel"].values.tolist()]
            arr = np.asarray(ds_pf["coil_current"].values, dtype=float)
            # Expected dims: (current_channel, time)
            if arr.ndim == 2 and arr.shape[1] == pf_df.shape[0]:
                for i, ch in enumerate(channels):
                    col = ch  # keep FAIR-MAST label (e.g. "P2IL FEED", "SOL")
                    pf_df[col] = arr[i, :].astype(float)
                    exported_pf.append(col)
            elif arr.ndim == 2 and arr.shape[0] == pf_df.shape[0]:
                for i, ch in enumerate(channels):
                    col = ch
                    pf_df[col] = arr[:, i].astype(float)
                    exported_pf.append(col)
            else:
                raise RuntimeError(
                    f"Unexpected coil_current shape {arr.shape} vs time length {pf_df.shape[0]}"
                )
        else:
            for k in ds_pf.data_vars:
                arr = ds_pf[k].values
                if getattr(arr, "ndim", None) == 1 and arr.shape[0] == pf_df.shape[0]:
                    pf_df[k] = arr.astype(float)
                    exported_pf.append(k)
        pf_df.to_csv(out_inputs_dir/"pf_active_raw.csv", index=False)

        # Do NOT invent NaN placeholder pf_currents.csv. Production mapping must come from
        # explicit coil_map authority (pipeline apply_coil_map stage).

        # PF voltages: coil_voltage (voltage_channel, time) with verbatim channel labels.
        # Units from zarr attrs (FAIR-MAST declares V) — never assumed.
        voltage_meta: Dict[str, Any] = {
            "csv": None,
            "channels": [],
            "units": None,
            "attrs": {},
            "present": False,
        }
        if "coil_voltage" in ds_pf and "voltage_channel" in ds_pf.coords:
            v_channels = [str(x) for x in ds_pf["voltage_channel"].values.tolist()]
            v_arr = np.asarray(ds_pf["coil_voltage"].values, dtype=float)
            v_time = ds_pf[t_pf].values.astype(float)
            volt_df = pd.DataFrame({"time": v_time})
            if v_arr.ndim == 2 and v_arr.shape[1] == volt_df.shape[0]:
                for i, ch in enumerate(v_channels):
                    volt_df[ch] = v_arr[i, :].astype(float)
            elif v_arr.ndim == 2 and v_arr.shape[0] == volt_df.shape[0]:
                for i, ch in enumerate(v_channels):
                    volt_df[ch] = v_arr[:, i].astype(float)
            else:
                raise RuntimeError(
                    f"Unexpected coil_voltage shape {v_arr.shape} vs time length {volt_df.shape[0]}"
                )
            volt_path = out_inputs_dir / "pf_voltages_raw.csv"
            volt_df.to_csv(volt_path, index=False)
            v_attrs = {str(k): (str(v) if not isinstance(v, (int, float, bool, type(None))) else v)
                       for k, v in dict(ds_pf["coil_voltage"].attrs).items()}
            units = ds_pf["coil_voltage"].attrs.get("units")
            voltage_meta = {
                "csv": "inputs/pf_voltages_raw.csv",
                "channels": v_channels,
                "units": (str(units) if units is not None else None),
                "attrs": v_attrs,
                "present": True,
                "n_times": int(volt_df.shape[0]),
            }
        else:
            voltage_meta["note"] = "coil_voltage or voltage_channel missing from pf_active.zarr"

        mag_df = pd.DataFrame({"time": t})
        flux_vars = [k for k in ds_mag.data_vars if ("flux" in k.lower() or "loop" in k.lower())]
        pickup_vars = [k for k in ds_mag.data_vars if ("pickup" in k.lower() or "probe" in k.lower() or "b_" in k.lower())]
        for k in (flux_vars[:80] + pickup_vars[:160]):
            arr = ds_mag[k].values
            if getattr(arr, "ndim", None) == 1 and arr.shape[0] == mag_df.shape[0]:
                mag_df[k] = arr.astype(float)
        mag_df.to_csv(out_inputs_dir/"magnetics_timeseries.csv", index=False)

        # Per-probe 2-D traces (channel, time) on the shared magnetics timebase.
        # Convention (v10.3.0): one CSV per probe family, columns named by the
        # FAIR-MAST channel coordinate values VERBATIM:
        #   inputs/flux_loops.csv  <- flux_loop_* data vars (e.g. flux_loop_flux, Wb)
        #   inputs/pickups.csv     <- b_field_*_probe_*_field data vars (T)
        # Only variables sampled on the SAME time axis as Ip are exported; probe
        # families on other timebases (time_mirnov/time_saddle/...) are skipped
        # and recorded in extract_meta. Units are copied from zarr attrs, never
        # assumed.
        probe_families = self._extract_probe_families(ds_mag, t_mag, t, out_inputs_dir)

        return {
            "t0": t0,
            "ip0": ip0,
            "ip_max": ip_max,
            "ip_var": ip_var,
            "pf_vars_exported": exported_pf,
            "pf_voltages": voltage_meta,
            "flux_vars_found": flux_vars[:80],
            "pickup_vars_found": pickup_vars[:160],
            "probe_families": probe_families,
        }

    def _extract_probe_families(self, ds_mag, t_mag: str, t, out_inputs_dir: Path) -> Dict[str, Any]:
        """Export 2-D per-probe traces to family CSVs with verbatim channel names.

        Returns a report dict recorded in extract_meta (files, variables, units,
        channel names, and skipped variables with reasons). Fails fast on
        duplicate channel names within a family (never silently overwrite).

        v10.4.0: probe families sampled on OTHER timebases (time_mirnov /
        time_saddle / time_omaha) are additionally exported VERBATIM for audit
        under inputs/audit_other_timebase/, with explicit evidence-based
        reasons why they cannot be honestly scored (see _audit_other_timebase).
        """
        import numpy as np
        import pandas as pd

        n_time = int(t.shape[0])
        family_frames: Dict[str, "pd.DataFrame"] = {}
        report: Dict[str, Any] = {
            "convention": "inputs/<family>.csv, columns = FAIR-MAST channel names verbatim",
            "families": {},
            "skipped_2d_vars": [],
        }

        def classify(var_name: str) -> str | None:
            if var_name.startswith("flux_loop"):
                return "flux_loops"
            if "_probe_" in var_name and var_name.endswith("_field"):
                return "pickups"
            return None

        for k in sorted(ds_mag.data_vars):
            v = ds_mag[k]
            if getattr(v, "ndim", 0) != 2:
                continue
            dims = list(v.dims)
            if t_mag not in dims:
                report["skipped_2d_vars"].append({"var": k, "reason": f"not_on_shared_timebase:{dims}"})
                continue
            chan_dim = dims[0] if dims[1] == t_mag else dims[1]
            if chan_dim not in ds_mag.coords:
                report["skipped_2d_vars"].append({"var": k, "reason": f"no_channel_coordinate:{chan_dim}"})
                continue
            family = classify(k)
            if family is None:
                report["skipped_2d_vars"].append({"var": k, "reason": "no_family_rule"})
                continue

            channels = [str(x) for x in ds_mag[chan_dim].values.tolist()]
            arr = np.asarray(v.values, dtype=float)
            if dims[0] == t_mag:
                arr = arr.T  # normalize to (channel, time)
            if arr.shape != (len(channels), n_time):
                report["skipped_2d_vars"].append(
                    {"var": k, "reason": f"shape_mismatch:{arr.shape} vs ({len(channels)},{n_time})"}
                )
                continue

            df = family_frames.setdefault(family, pd.DataFrame({"time": t}))
            dup = [ch for ch in channels if ch in df.columns]
            if dup:
                raise RuntimeError(
                    f"Duplicate probe channel names in family '{family}' from {k}: {dup}. "
                    "Refusing to overwrite experimental columns."
                )
            for i, ch in enumerate(channels):
                df[ch] = arr[i, :]

            units = v.attrs.get("units")
            fam_rep = report["families"].setdefault(family, {"csv": f"inputs/{family}.csv", "variables": {}})
            fam_rep["variables"][k] = {
                "units": (str(units) if units is not None else None),
                "channel_dim": chan_dim,
                "n_channels": len(channels),
                "channels": channels,
            }

        for family, df in family_frames.items():
            df.to_csv(out_inputs_dir / f"{family}.csv", index=False)

        report["audit_other_timebase"] = self._audit_other_timebase(ds_mag, t_mag, out_inputs_dir)

        return report

    @staticmethod
    def _audit_other_timebase(ds_mag, t_mag: str, out_inputs_dir: Path) -> Dict[str, Any]:
        """Extract probe families on OTHER timebases verbatim, for audit (default).

        Honest policy (authority-hardening, v10.6.0): these families are NOT
        contracted by default. Production calibrated CSVs + optional contracts
        require an explicit ``diagnostic_calibration`` authority (never invented
        V→T / V→Wb). Until that authority provides per-channel entries, traces
        stay under inputs/audit_other_timebase/ only.

        Evidence recorded per variable (from the shot's own zarr attrs):
          - units == 'V'  -> raw digitizer volts; no published V->T / V->Wb
            sensitivity in Level-2 attrs (geometry attrs: calibration "None";
            omaha label 'arb'). Optional calibration authority can supply scale.
          - units vs label contradiction (e.g. units='T' vs label='Tesla/sec'
            for mirnov, units='T' vs label='mT' for saddle): resolved ONLY via
            explicit unit_resolution in diagnostic_calibration — never silently.
          - FreeGSNKE 3.0.1 Probes synthesizes only point flux loops (psi, Wb)
            and point pickup coils (B.n, T); no saddle surface-flux model.
            OMV/CC_MV point probes exist in machine_authority geometry and may
            be synthesized after calibration to T with synthesize=true.

        Traces are written verbatim (native timebase, channel names verbatim).
        """
        import numpy as np
        import pandas as pd

        audit_dir = out_inputs_dir / "audit_other_timebase"
        out: Dict[str, Any] = {
            "convention": (
                "inputs/audit_other_timebase/<variable>.csv, columns = time,<FAIR-MAST channel names verbatim>; "
                "audit-only by default; promote via diagnostic_calibration authority "
                "(see contract_exclusion_reasons / awaiting_optional_diagnostic_calibration_authority)"
            ),
            "variables": {},
        }

        for k in sorted(ds_mag.data_vars):
            v = ds_mag[k]
            if getattr(v, "ndim", 0) != 2:
                continue
            dims = list(v.dims)
            if t_mag in dims:
                continue
            time_dims = [d for d in dims if str(d).startswith("time") and d in ds_mag.coords]
            if not time_dims:
                continue  # e.g. saddle geometry polylines (channel, coordinate)
            tdim = time_dims[0]
            chan_dim = dims[0] if dims[1] == tdim else dims[1]
            if chan_dim not in ds_mag.coords:
                continue

            channels = [str(x) for x in ds_mag[chan_dim].values.tolist()]
            t_native = np.asarray(ds_mag[tdim].values, dtype=float)
            arr = np.asarray(v.values, dtype=float)
            if dims[0] == tdim:
                arr = arr.T  # normalize to (channel, time)
            if arr.shape != (len(channels), t_native.shape[0]):
                out["variables"][k] = {"error": f"shape_mismatch:{arr.shape} vs ({len(channels)},{t_native.shape[0]})"}
                continue

            units = v.attrs.get("units")
            label = v.attrs.get("label")
            units_s = str(units) if units is not None else None
            label_s = str(label) if label is not None else None

            reasons = [
                "not_on_shared_magnetics_timebase:" + str(tdim),
                "awaiting_optional_diagnostic_calibration_authority",
            ]
            # Point-pickup families (OMV / CC mirnov) CAN use FreeGSNKE after
            # calibration to T; saddle/omaha cannot without inventing geometry/models.
            fam = str(k).lower()
            if "saddle" in fam:
                reasons.append(
                    "no_freegsnke_saddle_synthesizer (28-point polyline path flux; "
                    "calibrate for audit/future contracts only)"
                )
            elif "omaha" in fam:
                reasons.append(
                    "no_omaha_rz_in_machine_authority (cannot synthesize without inventing metrology; "
                    "calibrate experimental only)"
                )
            elif "omv" in fam or ("_cc_" in fam and "ccbv" not in fam):
                reasons.append(
                    "freegsnke_point_pickup_synth_gated_on_diagnostic_calibration "
                    "(geometry may exist; requires units_out=T + synthesize + syn_probe)"
                )
            else:
                reasons.append(
                    "no_freegsnke_synthesizer_for_family (Probes API supports only point flux loops and point pickups)"
                )
            if units_s == "V":
                reasons.append(
                    "raw_voltage_units_V_no_published_calibration_in_level2_attrs"
                    + (f" (label={label_s!r})" if label_s else "")
                    + "; supply diagnostic_calibration.channels[].scale to promote"
                )
            elif units_s is not None and label_s is not None and label_s not in (units_s, ""):
                reasons.append(
                    f"unit_metadata_contradiction:units={units_s!r},label={label_s!r}; "
                    "resolve only via diagnostic_calibration.unit_resolution"
                )

            audit_dir.mkdir(parents=True, exist_ok=True)
            data = {"time": t_native}
            for i, ch in enumerate(channels):
                data[ch] = arr[i, :]
            csv_path = audit_dir / f"{k}.csv"
            pd.DataFrame(data).to_csv(csv_path, index=False, float_format="%.8g")

            out["variables"][k] = {
                "csv": f"inputs/audit_other_timebase/{k}.csv",
                "timebase": str(tdim),
                "n_time": int(t_native.shape[0]),
                "n_channels": len(channels),
                "channels": channels,
                "units": units_s,
                "label": label_s,
                "uda_name": (str(v.attrs["uda_name"]) if v.attrs.get("uda_name") is not None else None),
                "finite_fraction": float(np.isfinite(arr).mean()),
                "contract_exclusion_reasons": reasons,
            }

        return out
