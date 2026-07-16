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
User input:  shot number (digits)
Output:      runs/shot_<N>/ with FreeGSNKE results + metrics + provenance
```

## Current gaps to close (in order)

1. **Interactive launcher** (`interactive_run.py`, `run_pipeline.cmd/.sh`)
   - Prompt **only** for shot (and optional `q` quit)
   - All other knobs from `configs/default.json`
   - Default: execute FreeGSNKE (`both`) + contract metrics **on** when paths exist

2. **CLI** (`mast-freegsnke run --shot N`)
   - Machine/config defaults from shipped config; `--machine` optional if `machine_authority_dir` set
   - `--execute-freegsnke` / metrics should be config-driven defaults for production config

3. **Authorities must be binding**
   - Coil map must drive PF mapping (not only validate)
   - Contracts must resolve relative to the run dir (no hardcoded `shot_00000`)
   - Template/`CHANGE_ME` machine authority must fail closed

4. **Prereq doctor**
   - Before download: `s5cmd`, network endpoint, machine authority validity, FreeGSNKE python
   - Fail with one actionable message per missing prereq

## Implementation checklist

```
- [ ] interactive_run: shot-only prompts
- [ ] default.json: execute_freegsnke=true, freegsnke_run_mode=both when ready
- [ ] coil_map wired into map_pf / templates
- [ ] contracts shot-scoped resolution
- [ ] doctor covers FreeGSNKE + s5cmd + authority
- [ ] end-to-end smoke on one public shot
```

## How to run (target UX)

Windows:

```cmd
run_pipeline.cmd
:: prompts: shot number only
```

Non-interactive:

```bash
mast-freegsnke run --shot 30201 --config configs/default.json
```

## Success criteria

- No y/n for execute/metrics in happy path
- `runs/shot_<N>/manifest.json` status success (or clear blocking_errors)
- Inverse and/or forward logs under `runs/shot_<N>/logs/`
- Provenance written under `runs/shot_<N>/provenance/`

## Related

- Philosophy gaps: see skill `authority-hardening`
- Reviewer pack: see skill `certify-run`
- Detail: [reference.md](reference.md)
