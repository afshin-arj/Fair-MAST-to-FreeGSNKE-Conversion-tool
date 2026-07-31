# GSFit Green’s authority (ADR-006)

**Status: awaiting_authority**

Place cited Green’s / response matrices for classic MAST sensors and coils here.
GSFit stores Green’s on **sensors** (bp_probes, flux_loops, rogowski, plasma grid)
linked to coil names — see GSFit README §2.3.

## Required before `gsfit_authority.status=ready`

1. Populate matrices with **cited** provenance (DOI, UDA note, institutional pack).
2. Write `provenance.json` in this directory with:
   - `status`: `cited` (not `awaiting_authority`)
   - `source`: citation string
   - `files`: list of matrix filenames + sha256 hashes
3. Never invent Green’s from FreeGSNKE or copy ST40/MAST-U silently.
4. Sensor/coil names must match `machine_authority/probe_geometry.json` and coil_map.

## Expected layout (illustrative)

```
gsfit_greens/
  provenance.json
  bp_probes_pf.npz          # or .npy / .h5 — declare format in provenance
  flux_loops_pf.npz
  ...
```

Until `provenance.json` has `status=cited` and at least one hashed file, the GSFit
stage remains soft-skipped.
