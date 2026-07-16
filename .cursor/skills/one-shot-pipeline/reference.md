# One-shot pipeline — reference

## Stage order (frozen)

1. machine_authority snapshot (if present)
2. mastapp_shot_exists
3. s3_shot_preflight
4. availability_check
5. download_groups
6. extract_csv
7. generate_scripts
8. execution_authority write
9. window (override > consensus > single-signal) + QC
10. probe_geometry → magnetic_probes.pickle
11. freegsnke_execute (inverse / forward / both)
12. coil_map resolve + apply
13. synthetic_extract + residual_metrics
14. provenance / manifest_v2

## Key files

| Path | Role |
|------|------|
| `src/mast_freegsnke/pipeline.py` | Stage orchestration |
| `src/mast_freegsnke/interactive_run.py` | User prompts (must become shot-only) |
| `src/mast_freegsnke/cli.py` | CLI entry |
| `configs/default.json` | Happy-path defaults |
| `templates/*.tpl` | FreeGSNKE drivers |
| `machine_authority/` | Geometry + registry (must be real, not fake) |

## Public MAST S3 (default.json)

- prefix: `s3://mast/level2/shots`
- endpoint: `https://s3.echo.stfc.ac.uk`
- `s3_no_sign_request`: true

## Blocking vs soft

Prefer blocking for: missing groups, invalid geometry (unless explicitly allowed), invalid coil map when metrics on, FreeGSNKE script failure when execute on, contracts failure when metrics on.

Soft/best-effort only when explicitly documented in stage policy.
