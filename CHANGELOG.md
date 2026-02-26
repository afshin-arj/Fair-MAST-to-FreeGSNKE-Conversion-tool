## 5.0.0
- Added cross-shot corpus indexing, atlas builder, certified atlas comparator, and deterministic regression guard.

# Changelog

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
