## 11.4.1 — L1 voltage inventory (P3/P6 stay I×R)
- **Inventory (shot 30201):** Level-1 `amc/` has P3/P6 currents only; no public `xpc` / `XPC_FA DRIVE`; `xma/p6_volts` (~40 mV raw) is **not** usable as FreeGSNKE PF drive. Evidence: `configs/l1_voltage_inventory_30201.json`.
- **No invented channels:** P3/P6 remain `from_current_ohmic`; honest_limits / README / machine provenance updated. Version **11.4.1**.

## 11.4.0 — Hardening: optional pf_passive, machine sync, doctor limits, certify
- **Doctor** prints `honest_limits` from machine provenance (wall≠CAD, no passives without ρ, P3/P6 I×R, copper 1.55e-8).
- **`optional_groups`**: best-effort `pf_passive` download for audit (non-blocking); `configs/passive_resistivity.json` awaits cited ρ (never invent).
- **`rebuild_machine_authority`**: fingerprints of `wall` + `pf_active` geometry; auto-rebuild classic pickles when they change (`machine-rebuild` CLI).
- **`mast-freegsnke certify`**: reviewer-pack + replay → `CERTIFY_REPORT.json` (GREEN/YELLOW/RED).
- Docs: stale `SHOTS/` → `SHOT/`; removed dead `machine_stub` + placeholder `machine_configs/`; evolutive notes classic-MAST-correct. Version **11.4.0**.

## 11.3.0 — Honest wall limiter + refined FAIR-MAST limits
- **Re-investigation:** FAIR-MAST Level-2 publishes `wall/` (`limiter_r`/`limiter_z`, EFIT limiter) and `pf_passive/` (parallelogram geometry). Production limiter/wall now comes from **`wall.zarr`**, not a flux-loop angle-sorted proxy.
- **Honest limits (documented + provenance):** EFIT wall limiter ≠ CAD vessel; **no FreeGSNKE passives** (`pf_passive` has geometry but **no resistivity** — do not invent ρ); **P3/P6** measured V absent → I×R only; active-coil **resistivity** = FreeGSNKE copper default **1.55e-8** (declared).
- `configs/default.json` `required_groups` includes `wall`. Flux-loop limiter kept only as explicit legacy fallback. Version **11.3.0**.

## 11.2.0 — Classic MAST FreeGSNKE machine from FAIR-MAST Level-2
- **Critical correction:** FAIR-MAST publishes **classic MAST**, not MAST-U. Production `machine_authority/` no longer uses FreeGSNKE public MAST-U-like pickles (divertors D1–D7/Dp/PX).
- **Builder:** `classic_mast_machine.py` + `scripts/build_classic_mast_machine.py` reads `pf_active.zarr` filaments → `active_coils.pickle` circuits `Solenoid, P2_inner, P2_outer, P3, P4, P5, P6`; limiter from `flux_loop_r/z` sorted by poloidal angle about centroid (computational, not CAD); passives empty; resistivity `1.55e-8` declared as FreeGSNKE copper default.
- **Authorities:** `voltage_map.json` classic order only; `p1→Solenoid`, `p2→P2_inner` and `P2_outer` (same-V policy), `p4→P4`, `p5→P5`; P3/P6 `from_current_ohmic`. Coil map circuit names match active keys. Doctor reports classic MAST (fails if divertors remain).
- Prior MAST-U-like pickles archived under `machine_authority/archive_mastu_like/`. Version **11.2.0**.

## 11.1.0 — FAIR-MAST voltages primary + window-cover evolutive + ohmic I×R
- **Honest voltage policy corrected:** FAIR-MAST Level-2 **does** supply measured voltages (`p1`/`p2`/`p4`/`p5`, units V) — these are the primary evolutive drive. The remaining mismatch is FreeGSNKE’s MAST-U-like structural divertor circuits vs classic MAST PF set (not “missing voltages”).
- **`from_current_ohmic`:** circuits with mapped FAIR-MAST currents but no voltage (P6 via coil_map `P6L+P6U`) build `V(t)=sign*scale*I(t)*R` using FreeGSNKE `evol_metal_curr.active_coil_resistances` after load; R snapshotted to `evolutive/coil_resist_snapshot.json`; fail-closed if R unavailable. Divertors D1–D7/Dp stay declared `default_V=0` (`machine_circuits_without_fairmast_drive`).
- **Window-length evolutive:** `cover_window=true` + `max_steps=50` + `full_timestep_s=0.02` → `n_steps=min(max_steps, ceil((t_end-t_start)/dt))` (shot 30201 ≈ 9 steps); optional `n_steps` override. `linear_only=true` default; `script_timeout_s` + `max_solving_iterations` bound runtime.
- **Optional profile law:** `scale_paxis_with_ip` (default **false** for smoke stability) scales `paxis` with measured `Ip(t)/Ip(t0)` when enabled — declared law, not invented numbers.
- Doctor banner: `N/M measured FAIR-MAST V; K by I×R; J by declared 0 V`. Version **11.1.0**.

## 11.0.0 — Evolutive forward + SHOT/ layout + repo rename
- **Evolutive forward from FAIR-MAST voltages:** extract `coil_voltage` → `inputs/pf_voltages_raw.csv` (units V from zarr attrs); binding `configs/voltage_map.json` maps `p1/p2/p4/p5` onto FreeGSNKE active circuit order (`Solenoid`, `PX`, …, `P4`, `P5`, `P6`) with explicit `default_V=0` for circuits without Level-2 voltage channels; snapshot+hash into `contracts/`.
- New `templates/evolutive_run.py.tpl` drives FreeGSNKE `nl_solver` / `initialize_from_ICs` / `nlstepper(active_voltage_vec=…)` using mapped voltages; numerics from fail-closed `configs/evolutive_authority.json` (default short window-friendly `n_steps=10`, `full_timestep_s=0.02`, `linear_only=true`). Profile parameters held from inverse IC — never invented.
- Happy path: `execute_evolutive: true` in `configs/default.json` (no new interactive prompts). Doctor validates voltage_map + evolutive_authority.
- **SHOT/<N>/** default `runs_dir` (was `SHOTS/`); expert overlay `00_README.txt` + `01_summary/SUMMARY.md` while keeping operational `inputs/` / `manifest.json` paths stable. `.gitignore` covers both `SHOT/` and `SHOTS/`.
- GitHub repo renamed to **fair-mast-freegsnke**; README rewritten with Mermaid diagrams; version **11.0.0**.

## 10.6.0 — Optional diagnostic calibration authority (mirnov/saddle/omaha)
- Convert mirnov / saddle / omaha from a hard forever-block into an **explicit optional authority**: `configs/diagnostic_calibration.json` ships with `status=awaiting_authority` and empty `channels` (no fabricated V→T / V→Wb numbers). Config key `diagnostic_calibration_path` points at it by default.
- Schema: per-channel `{source_variable, exp_column, units_in, units_out, scale, sign, offset?, source, notes, synthesize?, syn_probe?}` plus optional `unit_resolution` to resolve units-vs-label contradictions **only** via explicit declaration (never silent heuristics). Snapshot + SHA-256 into `SHOTS/<N>/contracts/`.
- When channels are populated: calibrated traces are written to production `inputs/mirnov.csv` / `inputs/saddle.csv` / `inputs/omaha.csv` in `units_out`; uncalibrated channels stay under `inputs/audit_other_timebase/`.
- FreeGSNKE synthesizer / identity contracts: only for `synthesize=true` mirnov/pickup point probes with `units_out` in {T, Wb} and a geometry `syn_probe` (OMV_*/CC_MV_* already in `machine_authority`). **Saddle**: no FreeGSNKE path-integral synthesizer (28-point polylines) — calibrate for audit/future only. **OMAHA**: no R/Z in machine_authority — experimental calibration only until geometry is imported honestly from FAIR-MAST.
- Doctor + interactive / CLI banner: one clear line — awaiting vs N channels calibrated & scored.
- Example template: `configs/diagnostic_calibration.example.json` (not wired by default; illustrative scales are placeholders).

## 10.5.0 — Full-inverse multi-time residual scoring (honest, capped)
- Multi-time synthetic diagnostics now prefer a **full FreeGSNKE inverse** (shape/profile optimisation via `Inverse_optimizer` + `NKGSsolver.inverse_solve`) at each `metrics_timebase` sample, not the forward-GS-at-measured-PF/Ip fallback.
- **Stall root cause (evidence-based):** reusing one `Inverse_optimizer` across sample times (or a bad residual-resize path) can hang inside FreeGSNKE 3.0.1's uncapped `while new_residual_flag:` loop in `GSstaticsolver.forward_solve` (called from `inverse_solve`), stuck in `freegs4e.critical.fastcrit` / `find_critical` while repeatedly shrinking the update (`update *= 0.75` / `reduce_by *= 0.75`) with **no iteration cap**. Declared FreeGSNKE knobs that matter: `max_solving_iterations` (outer inverse loop only — does **not** cap the inner residual-resize while), `target_relative_tolerance`, `target_relative_psit_update`, `l2_reg`. The hang is **not** cured by tightening tolerances alone.
- **Honest converging configuration (shot 30201, FreeGSNKE 3.0.1):** fresh `Inverse_optimizer` per sample time + cold-start of the multi-time loop (reset `plasma_psi` after the t0 inverse so it is not paired with a different time's measured PF) + sample-to-sample continuation thereafter + measured PF/Ip + `max_solving_iterations=50` + `inverse_target_relative_tolerance=1e-3`. Pipeline evidence (in-process): t=0.2012s → 19 iters, rel=6.46e-4 (inverse); t=0.2454s → 6, 4.63e-4 (inverse); t=0.2896s → inverse not_converged (50 iters, rel=1.35e-1) then forward_gs fallback; t=0.3338s → 1, 2.73e-4 (inverse); t=0.3780s → 1, 8.51e-5 (inverse). Overall `solve_mode=mixed_inverse_and_forward_gs` (4/5 inverse).
- New `solver.multitime` execution authority (snapshotted + hashed): `preferred_mode=full_inverse`, `fresh_constrain_per_time=true` (fail-closed if false), `continuation=true`, `max_solving_iterations=50`, `per_time_timeout_s=180`, `fallback_mode=forward_gs|skip`.
- Each sample-time solve runs **in-process** with declared `max_solving_iterations` and soft `per_time_timeout_s` accounting; FreeGSNKERunner also enforces `freegsnke_script_timeout_s` (default 1200) so the pipeline can never hang indefinitely. (A child-process isolation prototype was tried; on Windows each child rebuilds the tokamak and five solves exceeded the script budget — the stall itself is avoided by the fresh-constrain + continuation policy.)
- Per-time solve status (`converged` / `timeout` / `not_converged` / `skipped` / `completed_max_iter`) is recorded in `synthetic/synthetic_times.json` and embedded in metrics. Failed times fall back to forward-GS or are skipped — **never fabricated**.
- Version / docs / HOW_TO_RUN updated for solve_mode=`full_inverse`.

## 10.4.0 — Honest residual-metrics coverage: full contracts, shot-scoped NaN skip, multi-time scoring
- **A) Mirnov/saddle/omaha families investigated and honestly dispositioned.** New Level-2 evidence recorded per variable: `b_field_pol_probe_omv_voltage`, `b_field_tor_probe_saddle_voltage`, `b_field_tor_probe_omaha_voltage` are raw volts (omaha label `arb`) with no published V→T / V→Wb calibration factors anywhere in Level-2 attrs (geometry attrs state `calibration: "None"`); `b_field_pol_probe_cc_field` / `b_field_tor_probe_cc_field` declare `units: "T"` but `label: "Tesla/sec"` (self-contradictory unit metadata; flat-top amplitude ~1e-6 vs ~1e-1 T for the calibrated pickups, i.e. AC fluctuation signals); `b_field_tor_probe_saddle_field` declares `units: "T"` but `label: "mT"`; and FreeGSNKE 3.0.1 `Probes` synthesizes only point flux loops (psi) and point pickups (B·n) — no dB/dt fluctuation or saddle surface-flux model exists. No sensitivities were invented. These families are now extracted **verbatim for audit** onto their native timebases under `inputs/audit_other_timebase/<variable>.csv`, with per-variable evidence (units/label/uda_name/finite fraction/exclusion reasons) in `extract_meta.json`.
- **B) No more per-shot NaN hard-exclusions in the contracts authority.** `configs/diagnostic_contracts.json` now contracts ALL 93 identity-mapped channels of the shared-timebase families (15 flux loops + 40 CCBV + 19 OBV + 19 OBR pickups), including the 21 channels that are all-NaN on reference shot 30201. Metrics apply a **shot-scoped skip**: a contracted channel whose experimental trace has <2 finite samples on the current shot is reported as `skipped_all_nan` in `metrics/reconstruction_metrics.json` (`n_skipped_all_nan` + `skipped` list) — not a blocking failure, never a fabricated zero. Channels with real data still score.
- **C) Window-aware multi-time residual scoring.** New `metrics_timebase` execution authority (rule `linspace_window_inclusive`, config key `metrics_n_times`, default 5): after the t0 inverse solve, the runner performs an independent **forward-style Grad-Shafranov solve** (`constrain=None`) at each deterministic sample time inside the finalized window `[t_start, t_end]` with measured PF currents and Ip interpolated at that time, and emits one synthetic row per solved equilibrium plus `synthetic/synthetic_times.json` (rule + times + `solve_mode=forward_gs_at_measured_pf_ip`). Metrics interpolate experimental traces onto the solved times and compute RMS/MAE/max_abs across ALL sample times; the timebase record is embedded in the metrics summary and manifest. Never repeats a single solve across times. (Repeating the full inverse/shape optimization at every sample time stalls indefinitely under FreeGSNKE 3.0.1 for this MAST setup; the single t0 inverse remains the source of `inverse_dump.pkl` / plots / forward replay.)
- The `t0` formed-plasma solve is still performed first and remains the source of `inverse_dump.pkl` / plots / forward replay.

## 10.3.0 — Real contract-driven residual metrics
- Extractor exports FAIR-MAST 2-D per-probe traces onto the shared magnetics timebase as family CSVs:
  - `inputs/flux_loops.csv` from `flux_loop_flux` (`flux_loop_channel` × `time`, units Wb)
  - `inputs/pickups.csv` from `b_field_pol_probe_{ccbv,obv,obr}_field` (channel × `time`, units T)
  Channel names are FAIR-MAST coordinate values verbatim; units are copied from zarr attrs into `extract_meta`. Probe families on other timebases (mirnov/saddle/omaha) are skipped and reported.
- Inverse FreeGSNKE runner emits `synthetic/synthetic_fluxloops.csv` and `synthetic/synthetic_pickups.csv` via FreeGSNKE 3.0.1 `tokamak.probes` (`initialise_setup` + `calculate_fluxloop_value` / `calculate_pickup_value`) at the solved time slice `t0`.
- Ship `configs/diagnostic_contracts.json` (72 identity contracts after excluding 21 channels that are entirely NaN in FAIR-MAST Level-2 for reference shot 30201: 14 flux loops + 58 pickups). Flux-loop pairs declare the FAIR-MAST-internal rename `FL_<channel with / → _>` (corroborated by zarr attrs `label`/`uda_name` and `flux_loop_geometry_channel`); pickups use verbatim name identity. Units verified from zarr attrs (Wb / T). No fabricated scale factors.
- Enable `diagnostic_contracts_path` + `enable_contract_metrics=true` in `configs/default.json`. Metrics interpolate experimental traces onto the synthetic solve time(s); synthetic-extract and residual-metrics failures remain blocking when enabled.
- Docs / `contracts_status` updated to reflect the new reality.

## 10.2.0 — P1/P2 hardening: install hygiene, cache reuse, batch CLI, honest contracts status
- Launcher install hygiene: `RUN_PIPELINE_SKIP_INSTALL=1` skips pip upgrade/install entirely; otherwise `run_pipeline.cmd`/`run_pipeline.sh` reinstall only when `pyproject.toml` changed (SHA256 marker at `.venv/.install_marker`).
- Download cache reuse (`allow_cache_reuse`, default true): non-empty `data_cache/shot_<N>/<group>.zarr` trees are not re-synced; when every required group is cached the run skips MastApp REST, S3 preflight, availability, and sync entirely (no network). Per-group `download_report` (resolved S3 path, `cache_hit`, cheap file counts + bytes; no tree hashing) is recorded in the manifest and next to the cache.
- CLI batch mode: `mast-freegsnke run --shots N1 N2 ...` shares the exact loop/summary/worst-exit-code semantics with the interactive launcher (new `batch.run_shot_batch`).
- `batch_abort_on_failure` (default false): when true, a multi-shot batch stops at the first failing shot; remaining shots are reported as skipped in the summary.
- Path helpers `run_dir_for_shot(cfg, shot)` / `cache_dir_for_shot(cfg, shot)` centralize the `SHOTS/<N>` and `data_cache/shot_<N>` conventions (pipeline/cli/download refactored onto them).
- Diagnostic contracts decision (investigated, NOT wired): contract residual metrics stay disabled because channel identity cannot be established from repo data — the extractor exports only 1-D magnetics variables (FAIR-MAST per-probe traces such as `flux_loop_flux` are 2-D `(channel, time)` and are not extracted into named columns; shot 30201's `magnetics_timeseries.csv` contains only `time`), and the generated FreeGSNKE runners emit no synthetic probe CSVs under `SHOTS/<N>/synthetic/`. No scale/sign factors were fabricated. The launcher and `run` now print one clear line explaining the missing authority and how to provide it (`contracts_status.contract_metrics_status_line`).
- Docs updated to `SHOTS/<N>` paths and current flags (skills, run-doctor agent, AGENTS.md, README, HOW_TO_RUN.txt, config.example.json).

## 10.1.3 — Multi-shot launcher + SHOTS/<N> outputs + window authority fixes
- Interactive launcher accepts one or more shot numbers (space/comma separated); batch summary lists failed shots and exits with the worst code.
- Run outputs write to `SHOTS/<shot>` (e.g. `SHOTS/30201`) via `runs_dir` in `configs/default.json`.
- `run_pipeline.cmd` always pauses on exit (success or failure); set `RUN_PIPELINE_NO_PAUSE=1` to disable.
- Rerun hygiene: rerunning a shot archives the prior run into `SHOTS/<N>/history/<timestamp>/` (recorded in manifest as `prior_run_archived_to`); nothing is deleted.
- Fail-closed execution: FreeGSNKE inverse/forward are skipped when blocking errors already exist (extract/coil-map/geometry), recorded as `skipped_fail_closed_due_to_blocking_errors`.
- Window inference/QC/consensus now read the files extract actually writes (`ip.csv`, `magnetics_timeseries.csv`; legacy names still accepted).
- Consensus physics fix: Ip sources are authoritative for the formed-plasma window; PF proxy windows are audited but no longer vote when an Ip source exists (shot 30201 window corrected from pre-plasma −0.003..0.001 s to 0.201..0.378 s; QC confidence 0.0 → 0.65).

## 10.1.2 — Shot-only launcher hardening + FAIR-MAST Zarr stack
- `run_pipeline.cmd` / `run_pipeline.sh` are shot-only (no stale machine-authority flag; no y/n prompts).
- Prefer Python 3.11 when creating the pipeline venv; FreeGSNKE python path resolves across Windows/`bin` layouts.
- Pin `zarr>=3.1.0` so FAIR-MAST Level-2 `fixed_length_utf32` arrays extract correctly.
- Regression tests for interactive launcher wrappers and FreeGSNKE runner import hints.
- Verified end-to-end smoke: shot 30201 inverse + forward success under `configs/default.json`.
- Contract residual metrics remain opt-in (`enable_contract_metrics=false`) until a real diagnostic-contracts authority is shipped (no fabrication).

## 10.1.1 — Unblock full FreeGSNKE path
- Build `machine_authority/` from FAIR-MAST Level-2 geometry (no invented metrology).
- Export `coil_current` channels into `pf_active_raw.csv`; ship `configs/coil_map.json` with explicit feed sums.
- Resolve `s5cmd` via PATH or `tools/s5cmd.exe`; add `scripts/ensure_s5cmd.py`.
- Document FreeGSNKE in `.venv-freegsnke` (Python 3.11) via `freegsnke_python` in `configs/default.json`.

## 10.1.0 — Shot-only automation + authority binding
- Interactive launcher prompts for shot number only (config-driven defaults).
- CLI `--machine` optional when `machine_authority_dir` is set.
- Coil map authority now **applies** PF mapping (`apply_coil_map`); heuristic mapper demoted to suggest-only.
- Template/`CHANGE_ME` machine authority fail-closed; shipped probe geometry emptied.
- Shot-scoped diagnostic contract resolution (`resolve_contracts_for_run`) with `require_files=True` when metrics enabled.
- Doctor checks machine authority, coil map, and FreeGSNKE availability.
- Unmeasured residual-budget buckets omitted (not fake zeros).
- Fix `s5cmd sync` to use `/*` source trees (empty downloads were silently succeeding).
- `check`/`run` pass S3 endpoint + no-sign settings; absolute `s5cmd` paths accepted.

## 10.0.10
- Template Safety Authority: eliminate unsafe str.format() rendering for generated Python scripts; use token substitution to avoid brace collisions (f-strings/dicts).
- Added regression test for template rendering.

## 10.0.9
- Write full traceback to launcher log and runs/shot_<N>/EXCEPTION_TRACEBACK.txt on failure.

## v10.0.7 — S3 Transport Authority (endpoint/no-sign + timeout)

## 10.0.8
- Shot-scoped S3 preflight: avoid listing entire Level-2 shots prefix; probe only candidate shot roots derived from layout patterns.
- Pipeline stage renamed to s3_shot_preflight.

- Added config keys: `s3_endpoint_url`, `s3_no_sign_request`, `s5cmd_timeout_s`.
- Wired these into all `s5cmd` calls and added transport preflight.
- Added hard timeout to prevent indefinite hangs.

## v10.0.0 — FreeGSNKE Internal State Audit & Default-Elimination Authority

## 10.0.6

- Added shipped default config at `configs/default.json` (JSON is the canonical format).
- Interactive runner: default config path now `configs/default.json` and fails fast with a friendly message if config is missing.
- Config loader: now supports JSON and YAML (`.json` / `.yaml` / `.yml`) and correctly populates all AppConfig fields.
- Windows launcher: fixed `findstr` invocation to avoid `FINDSTR: Bad command line` noise.

## 10.0.5

- Fix Windows interactive runner: pass --machine (CLI contract) instead of --machine-authority.


## v10.0.1
## v10.0.2
- Windows launcher: switched logging from `Tee-Object` piping to PowerShell `Start-Transcript` to preserve interactive stdin (prevents apparent “freeze” / premature exit on prompts).
- Launchers: required inputs (shot number) now reprompt until valid (digits only) or user quits (`q`).
- Windows launcher: keeps the window open on error when launched by double-click (can disable via `RUN_PIPELINE_NO_PAUSE=1`).

- Launcher logging: `run_pipeline.cmd` and `run_pipeline.sh` now tee full stdout/stderr to timestamped logs under `logs/` for easy issue reporting.
- README updated with log-file locations and troubleshooting workflow.

- Added default-detection sentinel report: `solver_introspection/DEFAULT_DETECTION_REPORT.json` (mismatch flagged where discoverable).
- Added numerics trace evidence: `solver_introspection/numerics_trace.json` (best-effort convergence history extraction).
- Hardened profile basis governance via `profile_basis_authority.json` and `profile_basis` section in execution authority bundle.
- Updated FreeGSNKE script templates to write solver introspection artifacts automatically after inverse/forward runs.

## 5.0.0
- Added cross-shot corpus indexing, atlas builder, certified atlas comparator, and deterministic regression guard.

# Changelog

## v9.0.0 — FreeGSNKE Execution-State Authority (2026-02-26)
- Added execution authority bundle exported to `inputs/execution_authority/` for every run.
- Eliminated hidden defaults in generated `inverse_run.py` / `forward_run.py` by sourcing grid/profile/boundary/solver settings from the bundle.
- Embedded the authority bundle into `inverse_dump.pkl` for forward replay integrity.
- Updated generated `HOW_TO_RUN.txt` to require reviewing the authority bundle.

## v9.0.1 — One-command bootstrap launchers (2026-02-26)
- Added `run_pipeline.cmd` and `run_pipeline.sh` launchers that create/verify `.venv`, install dependencies, prompt for a shot number, and run the pipeline interactively.
- Updated `README.md` and `HOW_TO_RUN.txt` to document the launchers.

## v4.1.0 (2026-02-19)
- Added phase-consistency authority and scorecard outputs
- Added sensitivity attribution ledger and dominant failure modes report
- Added deterministic plot authority with plots manifest (SHA256)
- Robustness reviewer pack now includes new evidence artifacts and plots



All notable changes to this project are documented in this file.

## 1.2.0 — Documentation & examples (Git-ready)
- Professional, GitHub-ready `README.md` (installation, quick start, end-to-end workflow, geometry/contract authority).
- Added `examples/` onboarding suite with progressive workflows.
- Added `.gitignore`, `CHANGELOG.md`, and `LICENSE`.

## 1.1.0 — Diagnostic contracts + synthetic normalization + coil authority
- Added explicit diagnostic contracts mapping experimental ↔ synthetic diagnostics.
- Added contract-driven synthetic extraction normalization layer.
- Added PF/coil mapping authority schema + validator.

## 1.0.0 — FreeGSNKE execution harness + residual metrics
- Added subprocess execution harness with log capture.
- Added residual metrics engine (RMS/MAE/max residual).

## 0.9.0 — FreeGSNKE-native magnetic probe dict export
- Emitted `magnetic_probes.pickle` in FreeGSNKE-native dict format.



## v4.0.0 — Regime-Segmented Robustness & Continuity Authority
- Added v4 robustness package under src/mast_freegsnke/robustness
- Added CLI commands: robustness-run, robustness-pack
- Multi-window library generation around baseline window
- Deterministic DOE scenarios per window (window clipping, leave-one-out, contract scale perturbations)
- Stability tiering (GREEN/YELLOW/RED) and continuity metrics
- Robustness reviewer pack export


## v6.0.0 — Certified Physics-Consistency Authority
- Physics audit runner (closure tests + residual budget ledger)
- Physics-consistency tiering (PHYSICS-GREEN/YELLOW/RED)
- Physics audit reviewer pack + deterministic plots (hashed)
- Corpus closure atlas + comparator/regression-guard extensions


## v7.0.0 — Traceable Model-Form Error Authority
- Deterministic CV splits + forward checks from scenario outputs
- Model-form tiering (MFE-GREEN/YELLOW/RED)
- Consistency Triangle reviewer pack (robustness + physics + model-form)
- Atlas/comparator/regression-guard extensions for MFE


## v8.0.0 — Truth-by-Replay Authority
- replay-run: verifies artifacts vs declared hashes (strict/relaxed env closure)
- forensic-compare: deterministic divergence attribution + first-difference
- nondeterminism-check: replay hashing stability sentinel


## v10.0.4 — Windows interactive runner hardening (Python-driven prompts)
- Move interactive prompts out of cmd/bash into Python module to eliminate cmd.exe parser edge cases.
- run_pipeline.cmd/.sh now call python -m mast_freegsnke.interactive_run.
- README updated accordingly.

## v10.0.3
- Windows launcher: escaped parentheses in interactive prompts to avoid CMD parser errors like `. was unexpected at this time.` on some systems.
- Windows launcher: quit (`q`) now exits with code 0 (clean exit).