# GSFit authority activation checklist (ADR-006)

Use this when you have **cited** classic-MAST magnetics geometry, calibrations, and Green’s
tables and want the live GSFit peer stage to run for real.

Until then, leave `configs/gsfit_authority.json` at `status=awaiting_authority`. The pipeline
soft-skips and writes `SHOT/<N>/08_gsfit/GSFIT.md` with the same checklist.

## Steps

1. **Diagnostic calibration** — Populate `configs/diagnostic_calibration.json` `channels` with
   cited V→T / V→Wb (and `unit_resolution` where labels contradict). Never invent scales.
   Status must leave `awaiting_authority` with at least one channel.

2. **Green’s pack** — Place matrices under `machine_authority/gsfit_greens/`. Update
   `provenance.json`:
   - `status`: `cited`
   - `source`: DOI / UDA / institutional citation
   - `files`: list of filenames + sha256 hashes  
   Never invent Green’s; never silent-copy ST40 or MAST-U.

3. **Settings pack** — Edit `machine_authority/gsfit_settings/` JSON:
   - `status`: `ready` (not `awaiting_authority`)
   - Non-empty `sensors.*.include` lists and weights
   - Cited `p_prime` / `ff_prime` DoF and solver iteration policy

4. **Passives (optional)** — If vessel currents should enter the fit, cite classic-MAST ρ in
   `configs/passive_resistivity.json` (ADR-005). Until then GSFit passives stay empty.

5. **Install GSFit** — `pip install -r requirements-gsfit.txt` (or `pip install gsfit`) into the
   environment used for the pipeline / FreeGSNKE Python if that is where the stage runs.

6. **Flip authority** — Set `configs/gsfit_authority.json` `status` to `ready` (see
   `configs/gsfit_authority.example.json`). Keep `feed_targets_from_gsfit=false` unless a future
   ADR revisits target provenance.

7. **Re-run** — Shot-only path unchanged (`mast-freegsnke run --shot N`). Expect
   `08_gsfit/` products and the UI **GSFit** tab to leave awaiting. Complete the FAIR-MAST
   `database_reader` adapter if status is `adapter_incomplete`.

## Honest labels

- FreeGSNKE = happy-path solver  
- `04_efit_compare` = FAIR-MAST **EFIT++ archive** (not live)  
- `08_gsfit` = **live GSFit** peer (not EFIT++ / efit-ai / Py-EFIT)

ψ: GSFit COCOS 13 (Wb) vs scorecard Wb/2π — use `psi_to_scorecard_factor` from authority.
