# Cursor project agents & skills

North star: **user enters only a MAST shot number → FreeGSNKE results are produced automatically.**

## Rules (always / scoped)

| File | Role |
|------|------|
| `rules/north-star-shot-only.mdc` | Always-on product goal |
| `rules/authority-determinism.mdc` | When editing `src/mast_freegsnke/**` |
| `rules/ship-gate.mdc` | No commit/push until green; never force-push `main` |

## Skills (auto-discoverable)

| Skill | Use for |
|-------|---------|
| `skills/one-shot-pipeline` | Finish shot-only UX + defaults |
| `skills/authority-hardening` | Close silent-authority gaps |
| `skills/certify-run` | Reviewer packs + replay |
| `skills/ship-to-main` | Branch → commit → land on GitHub `main` |

Invoke by name in chat, e.g. “follow the one-shot-pipeline skill”.

## Subagents (`.cursor/agents/`)

| Agent | Use for |
|-------|---------|
| **`mast-freegsnke-super`** | **Orchestrates everything**: modify, test, run, then ship to `main` |
| `pipeline-orchestrator` | Implement end-to-end automation |
| `authority-auditor` | Philosophy compliance review (readonly) |
| `freegsnke-integrator` | Templates / execution / introspection |
| `run-doctor` | Diagnose `runs/shot_<N>/` failures (readonly) |

### Super-agent (recommended)

```
Use mast-freegsnke-super: finish shot-only automation, test, smoke-run,
then if green create a branch, commit, and land on GitHub main.
```

It loads all rules/skills, delegates to the specialists above, and only ships after gates pass (never force-push).

Ask the main agent to delegate specialists, e.g. “have authority-auditor review coil_map wiring”.

## Suggested first collaboration turn

1. Invoke **`mast-freegsnke-super`** for the full finish-and-ship loop, **or**
2. Delegate **authority-auditor** → **pipeline-orchestrator** → **run-doctor** manually.
