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

## Files to touch for coil_map wiring

- `src/mast_freegsnke/pipeline.py` (apply map before execute)
- `src/mast_freegsnke/generate.py` (stop embedding auto-map as production)
- `src/mast_freegsnke/coil_map.py`
- `templates/inverse_run.py.tpl` / `forward_run.py.tpl` if they read PF columns
- `tests/test_contracts.py` + new apply tests
