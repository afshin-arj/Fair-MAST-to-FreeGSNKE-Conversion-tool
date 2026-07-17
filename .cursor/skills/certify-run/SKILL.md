---
name: certify-run
description: >-
  Builds reviewer-grade evidence for a completed Fair-MAST → FreeGSNKE run:
  robustness, physics audit, model-form Consistency Triangle, reviewer pack,
  and truth-by-replay. Use when certifying a shot, exporting REVIEWER_PACK,
  running replay-run, forensic-compare, or regression-guard.
---

# Certify run

## When

After a successful `SHOTS/<N>/` exists with FreeGSNKE outputs (or after implementing certify CLI).

## Standard sequence

```bash
# Optional sensitivity layers (when ready)
mast-freegsnke robustness-run --run SHOTS/<N>
mast-freegsnke physics-audit-run --run SHOTS/<N>
mast-freegsnke model-form-run --run SHOTS/<N>
mast-freegsnke consistency-pack --run SHOTS/<N>

# Always for publish
mast-freegsnke reviewer-pack --run SHOTS/<N>
mast-freegsnke replay-run --target SHOTS/<N> --mode strict
```

## Target product command (implement when finishing tool)

```bash
mast-freegsnke certify --shot <N>
# runs: pipeline (if needed) → packs → replay; exits non-zero unless GREEN policy passes
```

## Pass criteria (reviewer grade)

- `manifest.json` status success, empty `blocking_errors`
- Provenance hashes present
- Machine authority snapshot hashed
- Replay report OK in strict mode (or relaxed for exported packs only)
- No template/`CHANGE_ME` markers in snapshotted authority

## Report back to user

- Path to `REVIEWER_PACK/` or `CONSISTENCY_TRIANGLE_REVIEWER_PACK/`
- Replay result
- Any RED/YELLOW tiers with file pointers
