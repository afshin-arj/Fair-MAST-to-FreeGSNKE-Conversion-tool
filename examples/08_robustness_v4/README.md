# Example 08 — v4 Robustness & Sensitivity (Multi-window DOE + Stability)

This example assumes you already completed a baseline run:

```bash
mast-freegsnke run --shot 30201 --config configs/config.json --machine machine_authority --enable-contract-metrics
```

Then run robustness analysis inside the created run directory:

```bash
mast-freegsnke robustness-run --run runs/shot_30201 --policy maximin
```

Export the robustness reviewer pack:

```bash
mast-freegsnke robustness-pack --run runs/shot_30201
```

Outputs are written to:

- `runs/shot_<N>/robustness_v4/`
- `runs/shot_<N>/robustness_v4/ROBUSTNESS_REVIEWER_PACK/`

Determinism contract:
- Scenario IDs are derived from canonical JSON (SHA256 → 16 hex chars).
- No stochastic sampling.
- Stable sorting is used for tie-breaking.
