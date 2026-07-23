# ADR-001: Optional FreeGSNKE → TORAX downstream coupling

- **Status:** accepted
- **Date:** 2026-07-23
- **Deciders:** project maintainers
- **Depends-on:** AGENTS.md design laws (explicit authority, fail-fast, no invented metrology)

## Context

Fair-MAST → FreeGSNKE is a **shot-only** pipeline: enter a MAST shot number → download FAIR-MAST Level-2 data → extract inputs → resolve declared authorities → run FreeGSNKE inverse/forward/evolutive Grad-Shafranov work → score residuals → write provenance. Happy-path prompts stay shot-only; missing authority fails closed.

[TORAX](https://github.com/google-deepmind/torax) (Google DeepMind) is a differentiable JAX core-transport simulator (heat / particle / current), with QLKNN and geometry ingest from CHEASE / FBT / EQDSK. Its [development roadmap](https://torax.readthedocs.io/en/latest/roadmap.html#development-roadmap) includes IMAS, multi-ion, and ML surrogates. Reference tree examined for this decision: [`b371a8513feef9323f338c8f623531597ecc11ef`](https://github.com/google-deepmind/torax/tree/b371a8513feef9323f338c8f623531597ecc11ef).

The two tools are **complementary**, not substitutes:

| Layer | Role |
|-------|------|
| FreeGSNKE | 2D equilibrium / magnetics |
| TORAX | 1D transport on flux surfaces |

Coupling is a plausible future export path. It must not erode the north star or invent physics.

## Decision

1. **Accept TORAX as an optional downstream consumer** of FreeGSNKE shot outputs. It is **not** part of the shot-only happy path by default (`mast-freegsnke run` / `run_pipeline` do not prompt for or require TORAX).

2. **Geometry export is authority-gated.** Any EQDSK (or time-series geometry) handed to TORAX must come from an **explicit** declared source: FreeGSNKE run products under a cited export contract, or a cited EFIT (or equivalent) authority. Missing / invalid export authority → **fail closed**. Do not invent equilibria, profiles, or calibration factors.

3. **FAIR-MAST measured Ip / profiles** may **validate or constrain** TORAX inputs only when real channels and diagnostic / contract authority exist. Absence of those channels is not filled with heuristics or placeholders.

4. **Out of scope until explicitly requested:** inventing TORAX source models, inventing QLKNN inputs, wiring TORAX into default pipeline prompts, or treating TORAX success as a gate for FreeGSNKE certification.

5. Future optional stages (if built) must **manifest** export outcomes and authority hashes in `manifest.json` / provenance, consistent with existing stage discipline.

## Consequences

**Positive**

- Keeps the shot-only path narrow and deterministic.
- Leaves a clear hook for transport follow-on without committing implementation now.
- Preserves fail-closed authority rules across any future FreeGSNKE → TORAX bridge.

**Negative / costs**

- No automatic transport closure today; users who want TORAX must opt in later via explicit config / authority.
- Geometry and profile readiness for TORAX may lag FreeGSNKE magnetics completeness until export authorities are written.

**Invariants (unchanged)**

- Do not invent metrology, probe geometry, or V→T / V→Wb factors.
- Do not invent TORAX physics numbers in docs, templates, or defaults.

## Alternatives considered

| Alternative | Why rejected |
|-------------|--------------|
| Embed TORAX in the default shot-only path | Violates north star (extra prompts / deps); TORAX needs authorities we do not invent. |
| Soft-continue with synthetic EQDSK / profiles when export authority is missing | Invents metrology; fails design laws 3–4. |
| Decline any TORAX coupling forever | Premature; complementary 2D↔1D use is scientifically useful once authorities exist. |
| Drive TORAX solely from uncited heuristics on FAIR-MAST tokens | Bypasses explicit authority; non-deterministic binding. |

## References

- Repo north star / laws: [`AGENTS.md`](../../AGENTS.md)
- TORAX source (pinned tree): https://github.com/google-deepmind/torax/tree/b371a8513feef9323f338c8f623531597ecc11ef
- TORAX roadmap: https://torax.readthedocs.io/en/latest/roadmap.html#development-roadmap
