# ADR-002: FAIR-MAST EFIT++ archive compare (Windows-friendly)

- **Status:** accepted
- **Date:** 2026-07-23
- **Deciders:** project maintainers
- **Depends-on:** AGENTS.md design laws; ADR-001 (optional downstream pattern)

## Context

Fusion experts on Windows want EFIT-like insights after a FreeGSNKE shot run.
Cloning and building [efit-ai](https://efit-ai.gitlab.io/efit/) (Fortran + Green’s tables + machine
namelists) is not a Windows-friendly happy path. FAIR-MAST Level-2 already publishes an
`equilibrium` Zarr group produced by **EFIT++** (shape scalars, LCFS, ψ map, β/q metrics).
[TokaMark](https://github.com/UKAEA-IBM-STFC-Fusion-FMs/tokamark) uses those same derived
signals as reconstruction targets — confirming they are the open, citeable EFIT archive for MAST.

## Decision

1. **Do not embed efit-ai Fortran** in the shot-only Windows path.
2. **Optional stage** `efit_compare` (default **on** for expert usefulness) downloads/reads
   FAIR-MAST `equilibrium` and compares FreeGSNKE products to the archived EFIT++ solve.
3. **Authority-gated** via `configs/efit_compare_authority.json` (snapshotted per run). Missing
   authority when compare is enabled → fail closed. Missing `equilibrium` group after download
   attempt → soft report (`ok=false`, clear fix hint) unless authority sets
   `fail_closed_if_missing=true`.
4. Outputs under `SHOT/<N>/04_efit_compare/` with honest labels:
   **FreeGSNKE** vs **FAIR-MAST EFIT++ archive** — never claim “we ran efit-ai.”
5. Happy path stays shot-only (no new interactive prompts). `equilibrium` is an
   **optional_groups** download when compare is enabled.

## Consequences

**Positive**

- Windows-native EFIT insights without Fortran toolchain.
- Validation against the same EFIT++ products TokaMark / FAIR-MAST experts already trust.
- Fail-closed on invented metrology; no Green’s table invention.

**Negative / costs**

- Compare quality depends on public L2 `equilibrium` coverage (NaNs at shot edges are expected).
- Does not re-solve EFIT; cannot replace institutional EFIT++ for control-room workflows.

**Out of scope**

- Installing or wrapping efit-ai / EFUND Green’s tables on Windows.
- Inventing MSE, diamagnetic, or probe σ weights.

## Alternatives considered

| Alternative | Why rejected |
|-------------|--------------|
| Clone efit-ai and run after FreeGSNKE | Not Windows-easy; needs MAST Green’s + namelists we do not invent |
| Soft-continue with synthetic EFIT fields | Invents metrology |
| Leave experts to open MastApp manually | Fails “easy for fusion experts” goal |

## Implementation status (v11.10.0)

| Piece | Status |
|-------|--------|
| Archive extract + LCFS/ψ plots | done |
| Shape scorecard (axis, midplane R, X-point, LCFS NN distance) | done (`shape_scorecard.csv`) |
| Declared ψ convention Wb/2π | done |
| Mode label `reconstruction_vs_archive` | done |
| Forward replay (EFIT currents+profiles → FreeGSNKE) | **not** implemented (needs cited profile-coeff authority) |

## Related

- [ADR-003](003-reject-pyefit-windows-path.md) — Py-EFIT / efit-ai / eqtools-as-solver are **not** the Windows path; FreeGSNKE + this archive compare remain.

## References

- FAIR-MAST Level-2 equilibrium docs: https://mastapp.site/level2-data.html
- TokaMark: https://arxiv.org/abs/2602.10132
- EFIT++ (Appel & Lupelli 2018) as FAIR-MAST derived provenance
- FreeGSNKE validated vs EFIT++ (MAST-U): https://arxiv.org/html/2407.12432v4
  (Pentland et al.; shape-control metric family used in our scorecard)
