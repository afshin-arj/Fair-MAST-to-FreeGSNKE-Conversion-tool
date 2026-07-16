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

        mag_df = pd.DataFrame({"time": t})
        flux_vars = [k for k in ds_mag.data_vars if ("flux" in k.lower() or "loop" in k.lower())]
        pickup_vars = [k for k in ds_mag.data_vars if ("pickup" in k.lower() or "probe" in k.lower() or "b_" in k.lower())]
        for k in (flux_vars[:80] + pickup_vars[:160]):
            arr = ds_mag[k].values
            if getattr(arr, "ndim", None) == 1 and arr.shape[0] == mag_df.shape[0]:
                mag_df[k] = arr.astype(float)
        mag_df.to_csv(out_inputs_dir/"magnetics_timeseries.csv", index=False)

        return {
            "t0": t0,
            "ip0": ip0,
            "ip_max": ip_max,
            "ip_var": ip_var,
            "pf_vars_exported": exported_pf,
            "flux_vars_found": flux_vars[:80],
            "pickup_vars_found": pickup_vars[:160],
        }
