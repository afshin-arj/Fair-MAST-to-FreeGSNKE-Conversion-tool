# Example 06 — Contract-driven scoring (diagnostic contracts + residual metrics)

Goal: compute residual metrics using explicit mapping between experimental and synthetic diagnostics.

## Commands

```bash
mast-freegsnke contracts-validate --contracts ../../configs/diagnostic_contracts.example.json
mast-freegsnke coilmap-validate --coil-map ../../configs/coil_map.example.json

mast-freegsnke run \
  --shot 30201 \
  --config ../../configs/config.example.json \
  --machine ../../machine_authority \
  --execute-freegsnke --freegsnke-mode both \
  --enable-contract-metrics \
  --contracts ../../configs/diagnostic_contracts.example.json \
  --coil-map ../../configs/coil_map.example.json
```

## Expected outputs

- `runs/shot_30201/contracts/diagnostic_contracts.resolved.json`
- `runs/shot_30201/contracts/coil_map.resolved.json`
- `runs/shot_30201/synthetic/*.csv`
- `runs/shot_30201/metrics/reconstruction_metrics.json`
