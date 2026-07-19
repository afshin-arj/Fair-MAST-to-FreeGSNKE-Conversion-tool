# Example 02 — Window inference (single-signal + consensus + QC)

Goal: infer a formed-plasma window deterministically and produce QC diagnostics.

## Commands

```bash
mast-freegsnke run --shot 30201 --config ../../configs/config.example.json --machine ../../machine_authority

# Recompute window only (if supported by your CLI build)
mast-freegsnke window --shot 30201 --config ../../configs/config.example.json

# Recompute QC only (if supported by your CLI build)
mast-freegsnke windowqc --shot 30201 --config ../../configs/config.example.json

# Consensus only
mast-freegsnke consensus --shot 30201 --config ../../configs/config.example.json
```

## Expected outputs

In `runs/shot_30201/inputs/`:
- `window.json`
- `window_consensus.json`
- `window_diagnostics.json`
- `WINDOW_QC_REPORT.txt`
