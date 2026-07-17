---
name: one-shot-pipeline
description: >-
  Implements and runs the shot-only Fair-MAST → FreeGSNKE happy path so the user
  only enters a shot number and gets download, windowing, geometry, FreeGSNKE
  execution, and metrics automatically. Use when finishing the tool, automating
  run_pipeline, simplifying interactive_run, or when the user says shot-only,
  one command, or automatic FreeGSNKE results.
---

# One-shot pipeline

## Goal

```text
User input:  shot number(s) (digits; space/comma separated)
Output:      SHOTS/<N>/ with FreeGSNKE results + provenance
```

## Current state (v10.2.0)

1. **Interactive launcher** (`interactive_run.py`, `run_pipeline.cmd/.sh`)
   - Prompts **only** for shot number(s) (and `q` quit); batch summary + worst exit code
   - All other knobs from `configs/default.json`
   - Executes FreeGSNKE (`both`) by default; contract metrics honestly disabled (no authority yet; one status line explains why)
   - `RUN_PIPELINE_SKIP_INSTALL=1` skips pip install; otherwise reinstall only when `pyproject.toml` changed (`.venv/.install_marker`)

2. **CLI** (`mast-freegsnke run --shot N` or `--shots N1 N2 ...`)
   - `--machine` optional (config `machine_authority_dir` is the default)
   - Batch mode shares the same loop/summary semantics as interactive (`batch.run_shot_batch`); `batch_abort_on_failure` stops at first failure

3. **Authorities are binding**
   - Coil map drives PF mapping (`apply_coil_map`); heuristics are suggest-only
   - Contracts resolve relative to the run dir (shot-scoped)
   - Template/`CHANGE_ME` machine authority fails closed

4. **Cache reuse** (`allow_cache_reuse=true`)
   - Non-empty `data_cache/shot_<N>/<group>.zarr` trees are not re-synced; full cache hit skips the network entirely; `download_report` in the manifest records cache hits + file counts/bytes

## How to run

Windows:

```cmd
run_pipeline.cmd
:: prompts: shot number(s) only
```

Non-interactive:

```bash
mast-freegsnke run --shot 30201 --config configs/default.json
mast-freegsnke run --shots 30201 30202 --config configs/default.json
```

## Success criteria

- No y/n for execute/metrics in happy path
- `SHOTS/<N>/manifest.json` status success (or clear blocking_errors)
- Inverse and/or forward logs under `SHOTS/<N>/logs/`
- Provenance written under `SHOTS/<N>/provenance/`

## Related

- Philosophy gaps: see skill `authority-hardening`
- Reviewer pack: see skill `certify-run`
- Detail: [reference.md](reference.md)
