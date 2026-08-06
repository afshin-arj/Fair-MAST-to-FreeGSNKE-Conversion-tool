# ADR-005: Classic-MAST passive resistivity citation (Path B5)

- **Status:** proposed (wiring ready; ρ / segment \(R\) still awaiting citation)
- **Date:** 2026-07-26
- **Updated:** 2026-08-04 (literature hunt notes)
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
science-blocked until a **cited** classic-MAST ρ table (or an explicitly accepted
segment-\(R\) authority mapped to FreeGSNKE filaments) exists.

Evolutive honesty today: `n_passive=0` + soft-stop (axis drift) is **correct**
under declared laws — not a mapping bug. CREATE-L / VALEN literature confirms
vessel eddy currents matter on classic MAST; empty pickles until citation is
intentional.

## Decision

1. **Do not invent** classic-MAST vessel/structure resistivity.
2. **Do not copy** MAST-U `passive_coils.pickle` ρ, FUSE.jl MAST-U cases, or
   FreeGSNKE MAST-U example passives onto classic MAST.
3. Populate `configs/passive_resistivity.json` **only** with published values and
   an explicit `source` citation (paper DOI, UDA/EFIT note, or UKAEA metrology
   memo). Prefer exact `pf_passive` stem names (`vertw`, `mid`, …); optional
   `default` / `*` applies the same cited ρ to unmatched stems.
4. When components are cited (status ≠ `awaiting_authority`),
   `write_classic_mast_machine` / `maybe_rebuild_classic_machine` rebuild
   `passive_coils.pickle` from FAIR-MAST geometry + cited ρ (ADR-005 wiring).
5. Until then: empty passives, certify warning `passive_resistivity_awaiting_authority`,
   planner notes passives excluded; evolutive soft-stop stays loud.
6. **Acceptable citation forms** (all require `source` + status `cited`):
   - Bulk material \(\rho\) (Ω·m) per structure stem, or
   - Documented conversion from cited segment **effective resistance** \(R_\mathrm{eff}\)
     + FAIR-MAST parallelogram geometry \(\rightarrow\) \(\rho\) (formula + inputs
     recorded in the authority notes — never silent).

## Citation hunt (literature status 2026-08)

| Candidate source | What to extract | Status |
|------------------|-----------------|--------|
| Berkery et al. 2021 PPCF 63 055014 / UKAEA-CCFE-PR(21)79 | VALEN 3D → ~18 EFIT vessel segments; **effective \(R\)** + loop voltage → \(I_\mathrm{vessel}\). Materials: stainless / Inconel (carbon tiles omitted). Method, not a ρ table. | **method cited** — numbers still **awaiting** supplemental / UKAEA memo |
| Artaserse et al. FED 88 (2013) 1091 (`10.1016/j.fusengdes.2012.12.033`) | CREATE-L linearized MAST model with **vessel + conducting structures** (eddy currents); validated vs EFIT / probes | **method cited** — no ρ table |
| Pangione et al. FED 88 (2013) 1087 (`10.1016/j.fusengdes.2013.01.048`) | rtEFIT + FIESTA + CREATE-L shape-control toolchain | context only |
| Classic-MAST EFIT++ / UDA vessel namelists | segment \(R_\mathrm{eff}\) or conductivity | **awaiting** |
| UKAEA metrology / machine description | Ω·m for named structures | **awaiting** |
| FreeGSNKE / FUSE.jl public **MAST-U** pickles / cases | — | **rejected** (wrong machine) |
| Buttery EX/S1-6; Valovič EX/P6-30; EUDAT mirror; Virtual Tokamak WILL | confinement / data / digital twin | **not ρ sources** |
| Appel & Lupelli CPC 223 (2018) iron-core EFIT++ | JET-like iron core | **out of scope** for classic MAST Path B5 |

Record the winning citation in each component’s `source` field and bump
`configs/passive_resistivity.json` `version` / `status` to `cited`.

## Science-grade roadmap (software phases)

| Phase | Status | Gate |
|-------|--------|------|
| 1 Honesty / scorecards | software | Forward `not_inverse_dn_peer`; Evolutive primary KPIs |
| 2 Cite classic-MAST ρ | **blocked** | Real DOI / UDA / UKAEA memo → populate `components` |
| 3 Passives A/B | blocked on 2 | Same shot with vs without passives |
| 4 Unclamped Ip campaign | opt-in authority | `clamp_ip_to_measured=false` — not happy-path default |

Until Phase 2 lands, `science_grade_roadmap.blocked_until` in
`configs/passive_resistivity.json` stays `cited_classic_mast_rho_or_R_eff`.

## Green’s functions (related, separate ADRs)

| Kind | Authority path | Notes |
|------|----------------|-------|
| FreeGSNKE active mutuals / vacuum Green’s | Cited coil geometry → solver | Already used for planner \(L\), isoflux |
| Passive–plasma / vessel Green’s in evolutive | Requires passives present | Blocked with ADR-005 |
| GSFit reconstruction Green’s pack | `machine_authority/gsfit_greens/` + provenance (ADR-006) | Never invent; never silent-copy ST40 / MAST-U |

## Consequences

- Path B5 can close once a real citation lands — no further geometry invention.
- Rebuild `machine_authority` after citing ρ; compare Ip/flux residuals with vs
  without passives.
- Planner UI ρ edits still require a machine rebuild to enter FreeGSNKE dynamics
  (existing foot-gun note retained).
- Agents/skills: use `passive-resistivity-path-b5` for citation work; never “fix”
  evolutive by inventing ρ.

## Rejected alternatives

- Soft-continue with steel “typical” 5.5e-7 Ω·m without citation.
- Import MAST-U / FUSE.jl / CREATE-L numerical decks without a classic-MAST citation.
- Disable evolutive soft-stops to fake a long GIF while `n_passive=0`.
- Claim Berkery/CREATE-L *papers alone* unlock Path B5 without numbers.
