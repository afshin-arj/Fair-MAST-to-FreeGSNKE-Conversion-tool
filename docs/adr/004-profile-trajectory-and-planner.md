# ADR-004: Profile trajectory authority + Python GSPulse-style planner

- **Status:** accepted (Phase 1 shipped; Phase 2b GSPulse-method planner shipped)
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
the feedforward planner stage (Phase 2 / Path B).

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

### Phase 2 / Path B (shipped through 2b): Idea B — Python GSPulse-method planner

Products are labeled `method=gspulse_python` (not upstream MATLAB/MEQ GSPulse). Authority version
`configs/planner_authority.json` **1.3.x** / method_version **v1.3**.

1. Stage `planner` (`execute_planner`, default **on** when coil_limits + circuit_dynamics
   are cited) solves a trajectory QP over the formed-plasma window:
   - cost: track measured PF currents + actuator effort + 1st/2nd derivative smoothness
     + optional vacuum-coil Green’s **isoflux** / x-point **B** + optional **ψ_bry**;
   - constraint: circuit dynamics \(L\dot{I}+R I = V\) with R/L from FreeGSNKE
     `build_tokamak_R_and_M` (active block; mutuals preferred when FreeGSNKE provides them);
   - box constraints from cited `coil_limits_authority`.
2. **Hard gate:** `configs/coil_limits_authority.json` must cite either fixed plant
   I/V limits **or** a declared `measured_peak_margin` policy (user: margin_factor=1.2
   over peak |measured I/V| in the planner window). Empty / `awaiting_authority` →
   planner blocked; **never invent Imax/Vmax silently**.
3. Outputs under `SHOT/<N>/07_planner/` (not `04_*` — that folder is EFIT compare):
   planned I/V CSVs, ΔI / ΔV residual plots, shape_targets / isoflux / Picard / plasma_scalars
   JSON, with honest labels for ohmic-synthetic P3/P6 channels. Dynamics voltages that still
   violate **fixed** cited plant V bounds after projection are **fail-closed**. Under
   `measured_peak_margin`, I boxes stay hard; V overshoot vs the 1.2× engineering envelope is
   reported as `voltage_exceeds_measured_peak_margin` (loud, not silent).
   **Voltage residual honesty (v11.32–v11.34):** planned V is post-map \(V=RI+L\dot{I}\) from the
   I-primary QP — not a least-squares fit to FAIR-MAST terminal V. Prefer
   `mean_i_track_rms_A` and `rms_plan_minus_dyn` / `voltage_model_gap.json` over raw ΔV.
   Annex fields: `mean_bias_plan_minus_meas_V`, early/late bias, `rms_RI_V`, `rms_L_dI_V`,
   `corr_V_dIdt`, `gap_status_label`. Solenoid/CS same-sign bias (often larger early under
   high \(|\dot{I}|\)) is active-only gap — not a p1 flip. **P4/P5 `voltage_map` sign=−1
   (v2.2)** restores \(\mathrm{corr}(V,\dot{I})>0\) under FreeGSNKE I convention; remaining
   residual is still active-only gap. `polarity_suspect` / sign-mismatch is YELLOW only for
   channels still anti-correlated after the declared map.
   Deferred ohmic (P3/P6) residuals score vs I×R_cited, not NaN.
   Default window end is `ip_prepeak_floor` (exclude pre-disruption Ip spike); does not close CS ΔV.
4. **Picard** (Path B3): optional outer loop — FreeGSNKE forward GS → freeze plasma ψ/B
   offsets → re-QP. Soft-skip when GS/profile inputs missing (`require_picard=false`).
5. **ψ_bry** (Path B4): archive boundary flux / Vloop integrate / Ejima only when **cited**
   Rp + L_I exist; otherwise `awaiting_authority` — never invent plasma circuit parameters.
6. Planner does **not** replace shot-only FreeGSNKE reconstruction or evolutive forward drive.
7. Passives excluded while `passive_resistivity` is `awaiting_authority` (Path B5 **blocked** —
   classic MAST vessel ρ must be cited; do not copy MAST-U).
8. `execute_planner=true` with `planner_authority.enabled=false` is a **blocking** error.
9. Certify is **YELLOW** when planner runs without successful isoflux and/or Picard (honesty gate).
10. UI Path **B6-full**: dedicated **Planner** tab (I/V, residuals, Picard, ψ_bry, authority
    hashes) + Compare A|B planner section; stage strip labels the `planner` stage.

Cited PF + Central Solenoid R/L live in `configs/circuit_dynamics_authority.json`.
Edit margin_factor / R/L / planner weights in JSON before a run (snapshotted into `inputs/`;
no new happy-path prompts).

## Implementation status

| Piece | Status |
|-------|--------|
| Phase 1 profile trajectory | done |
| Phase 2 coil_limits gate | done |
| Phase 2 circuit dynamics R/L snapshot | done (FreeGSNKE extract) |
| Phase 2 trajectory QP (numpy) | done |
| Phase 2 residual timeseries + ΔI/ΔV plots | done |
| Phase 2 V-limit fail-closed + no PF extrapolation | done |
| Phase 2 measured_peak_margin + user PF/CS R/L table | done |
| Phase 2 execute_planner default on | done |
| Path B0 honesty labels + certify YELLOW | done |
| Path B1 shape_targets from EFIT++ archive | done |
| Path B1b FreeGSNKE mutuals preferred | done |
| Path B2 vacuum-coil Green’s isoflux / x-point B | done |
| Path B3 Picard (forward GS freeze plasma offsets) | done (soft-skip) |
| Path B4 ψ_bry / Vloop / Ejima (cited Rp+L_I only) | done (soft-skip) |
| Path B5 passives in dynamics | **blocked** on classic-MAST `passive_resistivity` (wiring ready — ADR-005) |
| Path B6-thin Planner tab | done |
| Path B6-full Planner + Compare A\|B residuals | done |
| Path B7 this ADR Phase 2b + README honesty | done |

## Consequences

**Positive**

- Closes ADR-002’s profile-coeff gap for time-dependent FreeGSNKE profiles.
- Keeps shot-only happy path (no new prompts); soft-skip when archive lacks fit / shape / GS inputs.
- Phase 2b path is explicit, authority-gated, and visible in Planner / Compare UI.

**Negative / costs**

- `scalar_bridge` is underdetermined vs full p′/FF′; labeled honestly in provenance.
- Planner needs cited coil limits before it can run.
- Soft-skipped Picard / isoflux / ψ_bry remain YELLOW for certify — not a silent “full GSPulse”.
- Passives still absent until a citable classic-MAST ρ table exists.

## Out of scope

- Cloning GSPulse or requiring Octave/MATLAB / MEQ.
- Inventing V→T, Green’s tables, coil limits, vessel ρ, Rp, L_I, or p′/FF′.
- Replacing FreeGSNKE inverse / forward / evolutive with a planner in the happy path.
- Live EFIT++ / Py-EFIT (ADR-002/003).
- Copying MAST-U passive resistivity onto classic MAST.

## References

- Wai et al., Feedforward equilibrium trajectory optimization with GSPulse,
  *Nucl. Fusion* 66 016047 (2026); arXiv:2506.21760
- GSPulse public (reference only, not a dependency): https://github.com/jwai-cfs/GSPulse_public
- ADR-002: FAIR-MAST EFIT++ archive compare
- TokaMark (FAIR-MAST voltages as actuators; EFIT shape/flux as targets): arXiv:2602.10132
