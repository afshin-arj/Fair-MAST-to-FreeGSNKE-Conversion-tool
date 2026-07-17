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