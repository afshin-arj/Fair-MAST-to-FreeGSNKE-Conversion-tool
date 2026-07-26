# ADR-005: Classic-MAST passive resistivity citation (Path B5)

- **Status:** proposed (wiring ready; ρ still awaiting citation)
- **Date:** 2026-07-26
- **Deciders:** project maintainers
- **Depends-on:** AGENTS.md design laws; ADR-004 Path B5; `configs/passive_resistivity.json`

## Context

FAIR-MAST Level-2 `pf_passive` publishes classic-MAST parallelogram geometry
(`r`/`z`/`width`/`height`/`shapeAngle1`/`shapeAngle2`) for structures such as
`vertw`, `mid`, `ring`, `rodgr`, `coil_cases`, endcrowns, etc., but **does not**
publish resistivity. FreeGSNKE `passive_coils.pickle` entries require
`resistivity` (Ω·m). Inventing ρ or copying FreeGSNKE / MAST-U vessel values onto
classic MAST is forbidden.

ADR-004 Path B5 (planner / evolutive circuit dynamics with passives) remains
science-blocked until a **cited** classic-MAST ρ table exists.

## Decision

1. **Do not invent** classic-MAST vessel/structure resistivity.
2. **Do not copy** MAST-U `passive_coils.pickle` ρ onto classic MAST.
3. Populate `configs/passive_resistivity.json` **only** with published values and
   an explicit `source` citation (paper DOI, UDA/EFIT note, or UKAEA metrology
   memo). Prefer exact `pf_passive` stem names (`vertw`, `mid`, …); optional
   `default` / `*` applies the same cited ρ to unmatched stems.
4. When components are cited (status ≠ `awaiting_authority`),
   `write_classic_mast_machine` / `maybe_rebuild_classic_machine` rebuild
   `passive_coils.pickle` from FAIR-MAST geometry + cited ρ (ADR-005 wiring).
5. Until then: empty passives, certify warning `passive_resistivity_awaiting_authority`,
   planner notes passives excluded.

## Citation hunt (fill when found)

| Candidate source | What to extract | Status |
|------------------|-----------------|--------|
| Classic-MAST EFIT / UDA vessel notes | vessel / wall ρ or conductivity | **awaiting** |
| Peer-reviewed MAST (not MAST-U) passive papers | structure-resolved ρ | **awaiting** |
| UKAEA metrology / machine description | cited Ω·m for named structures | **awaiting** |
| FreeGSNKE public MAST-U pickles | — | **rejected** (wrong machine) |

Record the winning citation in each component’s `source` field and bump
`configs/passive_resistivity.json` `version` / `status` to `cited`.

## Consequences

- Path B5 can close once a real citation lands — no further geometry invention.
- Rebuild `machine_authority` after citing ρ; compare Ip/flux residuals with vs
  without passives.
- Planner UI ρ edits still require a machine rebuild to enter FreeGSNKE dynamics
  (existing foot-gun note retained).

## Rejected alternatives

- Soft-continue with steel “typical” 5.5e-7 Ω·m without citation.
- Import MAST-U passive resistivity as a stand-in for classic MAST.
