## v10.0.7 — S3 Transport Authority (endpoint/no-sign + timeout)

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
