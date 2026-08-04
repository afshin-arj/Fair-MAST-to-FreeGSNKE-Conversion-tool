---
name: passive-resistivity-path-b5
description: >-
  Classic-MAST passive resistivity (ADR-005 / Path B5): citation hunt for ρ or
  segment R_eff, wiring into passive_resistivity.json, machine rebuild, and
  honest n_passive=0 until cited. Use when enabling passives, fixing evolutive
  axis_drift / empty passive_coils, or reviewing vessel eddy-current literature.
---

# Passiveive resistivity — Path B5 (ADR-005)

## North star constraint

Shot-only happy path stays automatic. **Do not** invent vessel ρ, copy MAST-U /
FUSE.jl passives, or silence evolutive soft-stops to fake long GIFs.

## When to use

- Evolutive `n_passive=0`, `early_stop=axis_drift`, or certify `passive_resistivity_awaiting_authority`
- User asks how to get classic-MAST ρ / Green’s / vessel resistances
- Closing ADR-004 Path B5 (planner/evolutive dynamics with passives)

## Binding authorities

| File | Role |
|------|------|
| `configs/passive_resistivity.json` | Cited \(\rho\) (Ω·m) per `pf_passive` stem or `default`/`*` |
| FAIR-MAST Level-2 `pf_passive` | Geometry only (no ρ) |
| `machine_authority/passive_coils.pickle` | Built from geometry + cited ρ; empty until cited |
| `docs/adr/005-classic-mast-passive-resistivity.md` | Law + citation hunt table |

## Correct procedure (when a citation exists)

1. Add components to `passive_resistivity.json` with `resistivity_ohm_m` + `source` (DOI/memo).
2. Set `"status": "cited"` (and bump `version`).
3. Rebuild classic machine (`write_classic_mast_machine` / pipeline rebuild).
4. Re-run shot; certify should drop `passive_resistivity_awaiting_authority` when pickles non-empty.
5. Compare Ip / Raxis / flux residuals **with vs without** passives; keep soft-stops until validated.

## Citation hunt — preferred sources

**Method (numbers still usually missing — hunt supplemental / UKAEA notes):**

1. **Berkery et al. 2021** PPCF 63 055014 / UKAEA-CCFE-PR(21)79 — VALEN → EFIT vessel segment **\(R_\mathrm{eff}\)** + loop voltage.
2. **Artaserse et al. 2013** FED 88 1091 — CREATE-L MAST vessel eddy-current model (validates need for passives).
3. Classic **EFIT++ / UDA** vessel namelists or metrology memos with Ω·m or segment \(R\).

**Acceptable authority forms:** bulk \(\rho\), or documented \(R_\mathrm{eff}\) + geometry \(\rightarrow\) \(\rho\) with formula recorded in notes.

## Rejected / do not import

- FreeGSNKE or FUSE.jl **MAST-U** passive packs
- Typical steel \(\rho\) without citation
- Confinement papers alone (Buttery EX/S1-6, Valovič EX/P6-30)
- EUDAT / Virtual Tokamak WILL (data platforms, not ρ)
- Iron-core EFIT++ (Appel & Lupelli) for classic MAST Path B5
- Inventing GSFit Green’s or copying ST40/MAST-U Green’s (ADR-006 — separate)

## Green’s (do not conflate with ρ)

- FreeGSNKE **active** mutuals: from cited coil geometry (already).
- **Passive** coupling in evolutive: needs cited passives (this skill).
- GSFit Green’s pack: `machine_authority/gsfit_greens/` + provenance (ADR-006).

## Agent checks

- [ ] No invented Ω·m in JSON or templates
- [ ] `source` present on every component
- [ ] Machine rebuild after citation
- [ ] Evolutive titles/SUMMARY still honest if passives empty
- [ ] Tests: fail-closed awaiting; rebuild path when cited

## Related

- ADR-005, ADR-004 Path B5, ADR-006
- Skill `authority-hardening`
- Agents `authority-auditor`, `freegsnke-integrator`, `run-doctor`
