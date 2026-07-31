# ADR-006: GSFit live reconstruction peer (authority-gated scaffold)

- **Status:** accepted
- **Date:** 2026-07-31
- **Deciders:** project maintainers
- **Depends-on:** ADR-002 (EFIT++ archive); ADR-003 (no Py-EFIT/efit-ai); ADR-005 (passives ρ); AGENTS.md design laws

## Context

Experts want **EFIT-similar live reconstructions** from FAIR-MAST experimental magnetics on
Windows. ADR-002 supplies institutional insight via the Level-2 **EFIT++ archive** only.
ADR-003 rejected Py-EFIT / efit-ai / OMFIT-EFIT on the Windows happy path (Green’s + Fortran).

[GSFit](https://github.com/tokamak-energy/gsfit) (Tokamak Energy) is an open Grad-Shafranov
**fit** (reconstruction) with a Rust solver, Python UI, and **Windows PyPI wheels**. It is the
same *role* as EFIT++, not a FreeGSNKE substitute. Classic MAST still lacks cited diagnostic
calibration (V→T / V→Wb), Green’s tables, and GSFit settings / sensor weights. Until those
exist, any “live EFIT” solve would invent metrology.

## Decision

1. **Add optional stage `gsfit`** writing `SHOT/<N>/08_gsfit/` — live GSFit reconstruction
   peer, honestly labeled (**not** EFIT++ / efit-ai / Py-EFIT).
2. **Do not replace** ADR-002 archive compare or ADR-004 `profile_trajectory` /
   `shape_targets` derived from FAIR-MAST EFIT++.
3. **Do not replace** FreeGSNKE as the shot-only happy-path solver / evolutive engine.
4. Gate via `configs/gsfit_authority.json` (`status=awaiting_authority` by default). Soft-skip
   with a clear checklist when awaiting; **fail closed** if `execute_gsfit=true` and the
   authority file is missing, or if status is ready but `gsfit` cannot be imported, or if
   `require=true` and the solve is not ok.
5. Prerequisites (all cited — never invent): diagnostic calibration channels, Green’s authority
   pack + provenance, GSFit settings pack, probe geometry, coil_map / machine. Passives DoF
   honor ADR-005 (`passive_resistivity` awaiting → empty passives in the fit).
6. **COCOS:** GSFit uses COCOS 13 (ψ in Wb). Scorecards that compare to FreeGSNKE / EFIT++
   archive (Wb/2π) must apply the declared conversion in authority
   (`psi_to_scorecard_factor`, default `2*pi`) — never a silent convention.
7. **`feed_targets_from_gsfit`** remains `false` (future hook only). Targets stay EFIT++ archive.
8. Optional dependency: `gsfit` is **not** required in the base install while authority awaits
   (`requirements-gsfit.txt` / documented extra).
9. Happy path stays shot-only: `execute_gsfit=true` in default config; stage soft-skips with
   no new interactive prompts.

## Consequences

**Positive**

- Windows-native path to EFIT-like live solves once authorities are populated.
- Scaffold + UI ready today; activation is authority population + `pip install gsfit`.
- Preserves institutional EFIT++ archive validation (TokaMark / Pentland alignment).

**Negative / costs**

- Until calib + Green’s + settings are cited, `08_gsfit/` only reports `awaiting_authority`.
- Dual ψ conventions require explicit conversion in any three-way compare.

**Out of scope**

- Inventing Green’s, probe σ weights, or V→T scales.
- Replacing FAIR-MAST EFIT++ archive as the default reference / target source.
- Feeding GSFit products into FreeGSNKE profile/shape targets by default.

## Activation (when authorities exist)

See `docs/gsfit_authority_checklist.md`. Flip `gsfit_authority.status` to `ready` after
populating calibration, Green’s, and settings; install `gsfit`; re-run the shot.

## Related

- ADR-002: `docs/adr/002-fairmast-efit-compare.md`
- ADR-003: `docs/adr/003-reject-pyefit-windows-path.md`
- GSFit: https://github.com/tokamak-energy/gsfit
- Cite (unpublished): P. F. Buxton, GSFit, https://github.com/tokamak-energy/gsfit, 2025
