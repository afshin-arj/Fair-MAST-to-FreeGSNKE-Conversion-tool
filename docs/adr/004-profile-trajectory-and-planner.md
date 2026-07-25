# ADR-004: Profile trajectory authority + Python GSPulse-style planner

- **Status:** accepted (Phase 1 implemented; Phase 2 designed, not coded)
- **Date:** 2026-07-25
- **Deciders:** project maintainers
- **Depends-on:** AGENTS.md design laws; ADR-002 (EFIT++ archive); ADR-003 (no Py-EFIT path)

## Context

FreeGSNKE evolutive holds `alpha_m` / `alpha_n` / `fvac` from the inverse IC and only optionally
scales `paxis` with measured Ip (`scale_paxis_with_ip`). GSPulse (Wai et al. 2026 *Nucl. Fusion*)
is an evolutive **inverse** / pulse **planner**: time-dependent profile basis + shape targets +
circuit dynamics → planned coil I/V. Cloning GSPulse requires MATLAB/MEQ and is out of scope.

We want GSPulse **methods** in this Python + FreeGSNKE stack, using classic MAST geometry already
built from FAIR-MAST (`machine_authority/`), without inventing metrology.

ADR-002 deferred “forward replay (EFIT currents+profiles → FreeGSNKE)” pending a **cited
profile-coeff authority**. This ADR supplies that authority for evolutive drive (Phase 1) and
defines a later planner stage (Phase 2).

## Decision

### Phase 1 (shipped): Ideas E → A

1. **Do not** clone or vendor GSPulse / MATLAB / MEQ.
2. Stage **`profile_trajectory`** builds a declared
   `inputs/profile_trajectory_authority/profile_trajectory.json` from FAIR-MAST Level-2
   `equilibrium` (EFIT++ archive), never inventing missing fields.
3. Fit modes (authority-declared):
   - `archive_profiles` — least-squares fit of `ConstrainPaxisIp` knobs to archived
     `pprime`/`ffprime` (or pressure/f vs ψ) when present.
   - `scalar_bridge` — `paxis(t) = paxis_ref * wmhd(t) / wmhd_ref` with
     `alpha_m`/`alpha_n`/`fvac` fixed from execution authority; fail if `wmhd` missing for knots.
   - `auto` — prefer `archive_profiles` when profile arrays exist, else `scalar_bridge`.
4. When `require=false` (default) and the archive is insufficient → stage reports
   `skipped_insufficient_archive`; evolutive keeps IC hold (current behavior).
5. When `require=true` and fit cannot run → **blocking** error (certify path).
6. Evolutive consumes the trajectory when present: interpolated
   `(paxis, fvac, alpha_m, alpha_n)` at each step. Trajectory **overrides**
   `scale_paxis_with_ip` when both would apply; provenance records both.

### Phase 2 (designed only): Idea B — Python GSPulse-style planner

1. Optional stage `planner` (default **off**) solves a global QP over the formed-plasma window:
   - cost: isoflux/shape errors + actuator effort + 1st/2nd derivative smoothness
     (GSPulse cost structure);
   - constraint: circuit dynamics \(L\dot{I}+R I = V\);
   - GS Picard updates via FreeGSNKE (not MEQ);
   - mutuals/R from classic MAST FreeGSNKE machine; passives only when
     `passive_resistivity` is no longer `awaiting_authority`.
2. **Hard gate:** `configs/coil_limits_authority.json` must cite plant docs with non-empty
   I/V limits. Empty / `awaiting_authority` → planner blocked; **never invent Imax/Vmax**.
3. Outputs under `SHOT/<N>/04_planner/`: planned I/V CSVs + planning residual vs measured
   `pf_voltages.csv`, with honest labels for ohmic-synthetic P3/P6 channels.
4. Planner does **not** replace shot-only FreeGSNKE reconstruction or evolutive forward drive.

## Consequences

**Positive**

- Closes ADR-002’s profile-coeff gap for time-dependent FreeGSNKE profiles.
- Keeps shot-only happy path (no new prompts); soft-skip when archive lacks fit inputs.
- Phase 2 path is explicit and authority-gated.

**Negative / costs**

- `scalar_bridge` is underdetermined vs full p′/FF′; labeled honestly in provenance.
- Planner (Phase 2) needs cited coil limits before it can run.

## Out of scope

- Cloning GSPulse or requiring Octave/MATLAB.
- Inventing V→T, Green’s tables, coil limits, or p′/FF′.
- Replacing FreeGSNKE evolutive with a planner in the happy path.
- Live EFIT++ / Py-EFIT (ADR-002/003).

## References

- Wai et al., Feedforward equilibrium trajectory optimization with GSPulse,
  *Nucl. Fusion* 66 016047 (2026); arXiv:2506.21760
- GSPulse public (reference only, not a dependency): https://github.com/jwai-cfs/GSPulse_public
- ADR-002: FAIR-MAST EFIT++ archive compare
