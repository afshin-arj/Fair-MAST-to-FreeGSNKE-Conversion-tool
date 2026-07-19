# Example 03 — Geometry templates + validation

Goal: generate geometry templates, then validate/smoke-test geometry ingestion.

> Note: FAIR-MAST does not provide complete probe metrology; you must fill templates with authoritative values.

## Commands

```bash
mast-freegsnke geom-template --machine ../../machine_authority
mast-freegsnke geom-validate --machine ../../machine_authority
mast-freegsnke geom-smoke --machine ../../machine_authority
```

## Expected outputs

Inside `machine_authority/`:
- `probe_geometry.template.json`
- `flux_loops.template.csv`
- `pickup_coils.template.csv`

Validation writes a report describing missing/invalid fields.
