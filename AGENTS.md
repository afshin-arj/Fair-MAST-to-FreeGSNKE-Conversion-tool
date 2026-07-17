# AGENTS.md — Fair-MAST → FreeGSNKE

## North star

**The user enters only a MAST shot number. Everything else is automatic:** download FAIR-MAST Level-2 data → extract inputs → infer window → resolve machine/coil/contracts → generate FreeGSNKE scripts → execute inverse/forward → score residuals → write provenance.

No interactive prompts for config paths, geometry paths, execute y/n, or metrics y/n in the happy path.

## Design laws (never violate)

1. **Determinism** — no hidden optimization, smoothing, or silent conventions.
2. **Explicit authority** — machine, coil map, contracts, execution numerics are declared JSON, snapshotted, hashed.
3. **Fail fast** — missing/invalid authority is a blocking error, not a soft continue that invents metrology.
4. **Do not invent geometry** — templates must not look like real MAST probes.
5. **One binding mapping path** — coil_map authority drives PF mapping; heuristic `pf_map_rules` / auto-token scoring must not write production inputs silently.
6. **Manifest everything** — every stage outcome goes into `manifest.json` / provenance.

## Agent roles

| Agent | When to use |
|-------|-------------|
| `mast-freegsnke-super` | **Full loop**: audit → modify → test → run → branch → commit → land on GitHub `main` |
| `pipeline-orchestrator` | Implement or fix shot-only end-to-end automation |
| `authority-auditor` | Find philosophy violations (silent defaults, unwired authorities) |
| `freegsnke-integrator` | Wire FreeGSNKE execution, templates, introspection |
| `run-doctor` | Diagnose a failed `SHOTS/<N>/` |

## Skills

| Skill | When to use |
|-------|-------------|
| `one-shot-pipeline` | Make / run the shot-only path |
| `authority-hardening` | Close implicit authority gaps |
| `certify-run` | Reviewer-grade pack + replay verification |
| `ship-to-main` | Branch, commit, PR/merge onto GitHub `main` (never force-push) |

## Default implementation target

Prefer evolving toward:

```bash
mast-freegsnke run --shot <N>
# or: run_pipeline.cmd  → prompts ONLY for shot number
```

using shipped `configs/default.json` + populated `machine_authority/` + contracts/coil map resolved automatically for that shot.

## Out of scope unless asked

- Inventing probe metrology numbers
- Force-push / destructive git
- Committing secrets or large cached Zarr trees
