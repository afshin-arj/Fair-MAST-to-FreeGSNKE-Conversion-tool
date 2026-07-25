# ADR-004: Profile trajectory authority + Python GSPulse-style planner

- **Status:** accepted (Phase 1 shipped; Phase 2 v1 planner shipped, default off)
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

### Phase 2 (v1 shipped): Idea B — Python GSPulse-style planner

1. Optional stage `planner` (config `execute_planner`, default **on** when coil_limits +
   circuit_dynamics authorities are cited) solves a trajectory
   optimization over the formed-plasma window:
   - cost: track measured PF currents + actuator effort + 1st/2nd derivative smoothness
     (GSPulse cost vocabulary; full GS Picard isoflux deferred);
   - constraint: circuit dynamics \(L\dot{I}+R I = V\) with R/L from FreeGSNKE
     `build_tokamak_R_and_M` (active block);
   - box constraints from cited `coil_limits_authority`.
2. **Hard gate:** `configs/coil_limits_authority.json` must cite either fixed plant
   I/V limits **or** a declared `measured_peak_margin` policy (user: margin_factor=1.2
   over peak |measured I/V| in the planner window). Empty / `awaiting_authority` →
   planner blocked; **never invent Imax/Vmax silently**.
3. Outputs under `SHOT/<N>/07_planner/` (not `04_*` — that folder is EFIT compare):
   planned I/V CSVs + planning residual vs measured `pf_voltages.csv`, with honest labels
   for ohmic-synthetic P3/P6 channels. Dynamics voltages that still violate **fixed** cited
   plant V bounds after projection are **fail-closed**. Under `measured_peak_margin`,
   I boxes stay hard; V overshoot vs the 1.2× engineering envelope is reported as
   `voltage_exceeds_measured_peak_margin` (loud, not silent) without inventing plant ratings.
4. Planner does **not** replace shot-only FreeGSNKE reconstruction or evolutive forward drive.
5. Passives excluded while `passive_resistivity` is `awaiting_authority`.
6. `execute_planner=true` with `planner_authority.enabled=false` is a **blocking** error
   (not a silent success).
7. Cited PF + Central Solenoid R/L live in `configs/circuit_dynamics_authority.json`
   (user MAST tables). Edit margin_factor / R/L JSON before a run to retune
   (snapshotted into `inputs/`; no new happy-path prompts). `execute_planner` defaults
   **on** once those authorities are cited.

## Implementation status

| Piece | Status |
|-------|--------|
| Phase 1 profile trajectory | done |
| Phase 2 coil_limits gate | done |
| Phase 2 circuit dynamics R/L snapshot | done (FreeGSNKE extract) |
| Phase 2 trajectory QP (numpy) | done (current-tracking v1) |
| Phase 2 residual timeseries + ΔV plot | done |
| Phase 2 UI (Overview / Authorities / Compare) | done |
| Phase 2 V-limit fail-closed + no PF extrapolation | done |
| Phase 2 measured_peak_margin + user PF/CS R/L table | done |
| Phase 2 execute_planner default on | done |
| Phase 2 GS Picard isoflux cost | **not yet** (EFIT shape inventory only) |
| Phase 2 passives in dynamics | blocked on passive_resistivity |

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
