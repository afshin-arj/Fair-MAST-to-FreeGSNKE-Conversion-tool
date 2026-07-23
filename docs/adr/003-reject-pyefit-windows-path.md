# ADR-003: Reject Py-EFIT / eqtools-as-solver / efit-ai on Windows MAST path

- **Status:** accepted
- **Date:** 2026-07-23
- **Deciders:** project maintainers
- **Depends-on:** ADR-002 (FAIR-MAST EFIT++ archive compare); AGENTS.md design laws

## Context

Experts asked whether a Python “EFIT” stack can replace EFIT / EFIT++ on Windows using FAIR-MAST Level-1/2 data. Candidate links examined:

| Tool | Role |
|------|------|
| [eqtools](https://github.com/PSFCPlasmaTools/eqtools) | Read / map existing EFIT g/a-files and MDSplus trees — **not a solver** |
| [OMFIT mod_EFIT](https://omfit.io/modules/mod_EFIT.html) | Wrapper around **Fortran EFIT** + Green’s tables |
| [Py-EFIT (CPC 2022)](https://www.sciencedirect.com/science/article/abs/pii/S0010465522002685) | Python GS reconstruction demonstrated on **EAST** with EAST Green’s / DB |
| [efit-ai](https://efit-ai.gitlab.io/efit/) | Portable Fortran EFIT lineage; needs Green’s + namelists; not Windows-easy |
| [arXiv:2407.12432](https://arxiv.org/html/2407.12432v4) | Validates **FreeGSNKE** (and Fiesta) static forward against **EFIT++** on MAST-U |

FAIR-MAST L1/L2 supply magnetics-like measurements and publish archived `EFM_*` / `equilibrium` products; they do **not** ship MAST Green’s tables or EFIT++ namelists suitable for a bit-identical re-solve.

## Decision

1. **Do not integrate Py-EFIT, efit-ai, or OMFIT-EFIT** into the shot-only Windows happy path.
2. **Do not treat eqtools as a reconstruction engine.** Optional future use is limited to reading / mapping EQDSK or archived EFIT products under explicit authority (same fail-closed rules as ADR-001/002).
3. **Windows reconstruction engine remains FreeGSNKE** (inverse / forward / evolutive) fed by FAIR-MAST authorities.
4. **EFIT-like insight on Windows** remains ADR-002: compare FreeGSNKE to the FAIR-MAST Level-2 **EFIT++ archive** (`equilibrium` / `EFM_*`), honestly labeled — never “we ran Py-EFIT / EFIT++.”
5. Revisit only if a **cited MAST Green’s + machine + namelist authority** becomes available and a Linux (WSL/Docker) or institutional EFIT++ path is explicitly requested.

## Consequences

**Positive**

- Avoids a dead-end EAST/Fortran dependency that cannot honestly claim MAST EFIT++ parity.
- Aligns with published FreeGSNKE ↔ EFIT++ validation (arXiv:2407.12432).
- Keeps the shot-only path narrow and Windows-installable.

**Negative / costs**

- No live EFIT++ re-solve from FAIR-MAST on bare Windows.
- Archive compare quality tracks public L2 `equilibrium` coverage.

**Out of scope**

- Inventing Green’s tables, probe σ weights, or EAST→MAST Py-EFIT ports.
- Bundling Fortran EFIT / efit-ai in `requirements.txt`.

## Alternatives considered

| Alternative | Why rejected |
|-------------|--------------|
| Wire Py-EFIT for MAST shots | EAST Green’s/DB; no cited MAST response pack; would invent metrology to “make it run” |
| eqtools as “Python EFIT” | Reader only; cannot reconstruct from FAIR-MAST raw signals |
| efit-ai / OMFIT-EFIT on Windows | Not Windows-easy; needs Green’s + institutional plumbing |
| Soft-continue with synthetic Green’s | Violates design laws 3–4 |

## References

- ADR-002: `docs/adr/002-fairmast-efit-compare.md`
- FreeGSNKE vs EFIT++ (MAST-U): https://arxiv.org/html/2407.12432v4
- FAIR-MAST `EFM_*` → `equilibrium` mapping: https://github.com/ukaea/fair-mast-ingestion
- Py-EFIT (EAST): Bao et al., Comput. Phys. Commun. (2022)
- eqtools: https://eqtools.readthedocs.io/
