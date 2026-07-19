# Example 04 — Full run-folder generation (no FreeGSNKE execution)

Goal: produce a publishable run folder structure without executing FreeGSNKE.

## Commands

```bash
mast-freegsnke run --shot 30201 --config ../../configs/config.example.json --machine ../../machine_authority
```

## Expected outputs

In `runs/shot_30201/`:
- `inverse_run.py`, `forward_run.py`
- `magnetic_probes.pickle` (if geometry is valid)
- `inputs/`, `contracts/`, `synthetic/`, `metrics/`
- `manifest.json`
