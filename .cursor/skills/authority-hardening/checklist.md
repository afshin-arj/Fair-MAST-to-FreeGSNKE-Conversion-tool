# Authority hardening checklist

## Binding test (for each authority)

Ask: *If I change this JSON, does the FreeGSNKE run change?*

| Authority | Binding today? | Target |
|-----------|----------------|--------|
| machine / probe geometry | Yes (pickle export) | Keep; fail on template markers |
| execution_authority | Yes (scripts require bundle) | Keep; strict default detection |
| diagnostic contracts | Partial (metrics path) | Always resolve vs run dir |
| coil_map | No (validate only) | Wire into PF mapping + templates |
| pf_map_rules heuristic | Yes (dangerous) | Suggest-only or remove from happy path |
| passive_resistivity (ADR-005) | Binding when cited; empty pickle while awaiting | Cite ρ / \(R_\mathrm{eff}\) only; rebuild machine; never invent |

## Files to touch for coil_map wiring

- `src/mast_freegsnke/pipeline.py` (apply map before execute)
- `src/mast_freegsnke/generate.py` (stop embedding auto-map as production)
- `src/mast_freegsnke/coil_map.py`
- `templates/inverse_run.py.tpl` / `forward_run.py.tpl` if they read PF columns
- `tests/test_contracts.py` + new apply tests

## Files for Path B5 passives (only after citation)

- `configs/passive_resistivity.json`
- `docs/adr/005-classic-mast-passive-resistivity.md`
- classic machine rebuild (`write_classic_mast_machine` / `machine_sync`)
- Skill: `.cursor/skills/passive-resistivity-path-b5/SKILL.md`
