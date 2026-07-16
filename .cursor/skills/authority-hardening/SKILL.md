---
name: authority-hardening
description: >-
  Closes implicit-authority gaps in the Fair-MAST → FreeGSNKE pipeline: unwired
  coil maps, heuristic PF mapping, template fake geometry, hardcoded contracts,
  unmeasured residual zeros, and FreeGSNKE silent defaults. Use when hardening
  authorities, removing silent conventions, fixing coil_map wiring, or aligning
  code with determinism philosophy.
---

# Authority hardening

## Priority fixes (philosophy violations)

### P0 — Coil map must drive the run

- Today: `coil_map` validates/resolves; comment in `pipeline.py` says not wired into templates
- Today: `map_pf_currents.py` auto-rules / token scoring / mean-of-matches
- Target: production PF mapping uses **only** explicit coil_map; heuristics may print suggestions but never write production CSVs unless `--suggest-only`

### P0 — Template geometry fail-closed

- Reject `CHANGE_ME`, `TEMPLATE`, or empty provenance in `authority_manifest.json`
- `require_machine_authority: true` for production default when finishing the tool
- Do not ship plausible fake probe coordinates that can run FreeGSNKE

### P1 — Shot-scoped contracts

- Resolve `exp.csv` / `syn.csv` relative to `runs/shot_<N>/`
- When `--enable-contract-metrics`, default `--require-files`

### P1 — Residual budget honesty

- Unmeasured buckets → `"UNMEASURED"` (or omit), never `0.0` that looks like evidence

### P2 — Strict default detection

- In reviewer/certify mode, any FreeGSNKE default not in execution_authority → blocking

## Checklist when editing authorities

```
- [ ] Authority JSON schema validated
- [ ] Snapshot + hash written into run folder
- [ ] Downstream code actually reads the authority (not only validates)
- [ ] No parallel heuristic path can override it silently
- [ ] Tests cover fail-closed behavior
```

## Anti-patterns

- Soft-continue with invented numbers
- Dual systems (rules + coil_map) both writable
- Docs version ≠ `pyproject.toml` version without updating both

## Related

- [checklist.md](checklist.md)
- Skill `one-shot-pipeline` for UX wiring
- Agent `authority-auditor` for review passes
