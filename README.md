# MAST → FreeGSNKE Reconstruction Pipeline

A **deterministic** Python pipeline that turns a **MAST shot number** into a **publishable, replayable FreeGSNKE reconstruction run folder**.

The pipeline is designed for **auditability** (explicit decisions, no hidden iteration), and is structured to support GitHub publication and collaborative use.

**Author:** © 2026 Afshin Arjhangmehr

---

## 1. Overview

Given a shot number, the pipeline:

1. Verifies shot existence and required FAIR-MAST Level-2 groups.
2. Discovers and downloads Zarr datasets (via `s5cmd`).
3. Extracts required signals to CSV inputs.
4. Infers a formed-plasma time window (single-signal + consensus) with QC diagnostics.
5. Ingests and validates **machine probe geometry** (required for synthetic magnetics).
6. Generates a FreeGSNKE run folder:
   - `inverse_run.py`, `forward_run.py`
   - `magnetic_probes.pickle` (FreeGSNKE-native dict)
   - window + QC + provenance artifacts
7. Optionally executes FreeGSNKE runs and computes residual metrics under explicit **diagnostic contracts**.

---

## 2. Scientific Objective

Produce a reproducible and reviewer-safe workflow that reads experimental FAIR-MAST data and produces FreeGSNKE reconstructions including synthetic diagnostics.

**Key constraint:** determinism.
- No implicit optimization.
- No hidden smoothing.
- No silent conventions.
- All decisions logged into `manifest.json`.

---

## 3. Repository Architecture

Core package: `src/mast_freegsnke/`

- `mastapp.py` — shot existence check
- `availability.py` — required group pre-check
- `download.py` — S3 discovery + bulk download (via `s5cmd`)
- `extract.py` — Zarr → CSV extraction
- `windowing.py` — single-signal window inference
- `window_consensus.py` — multi-signal consensus (deterministic)
- `window_quality.py` — QC + confidence scoring
- `probe_geometry.py` — geometry ingestion/validation/export
- `generate.py` — run-folder generation + script templating
- `freegsnke_runner.py` — subprocess execution harness + logs
- `diagnostic_contracts.py` — explicit experimental↔synthetic mapping
- `synthetic_extract.py` — normalize FreeGSNKE outputs under contracts
- `metrics.py` — residual metrics (RMS/MAE/max) under explicit contracts

---

## 4. Installation

### 4.1 Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\\Scripts\\activate  # Windows
```

### 4.2 Install

```bash
pip install -e .
```

Optional extraction dependencies (Zarr stack):

```bash
pip install -e ".[zarr]"
```

Dev (tests):

```bash
pip install -e ".[dev]"
pytest -q
```

---

## 5. Quick Start (5-minute workflow)

### 5.0 One-command interactive launcher (recommended)

For a first run, use the interactive launcher. It will:

- create/activate a local `.venv`
- install this repo in editable mode (with `zarr,dev` extras)
- ask for a shot number and run options

Windows:

```cmd
run_pipeline.cmd
```

Linux/macOS:

```bash
./run_pipeline.sh
```

1) Validate FAIR-MAST groups for a shot:

```bash
mast-freegsnke check --shot 30201 --config configs/config.example.json
```

2) Run pipeline up to run-folder generation (no FreeGSNKE execution):

```bash
mast-freegsnke run --shot 30201 --config configs/config.example.json --machine machine_configs/MAST
```

Outputs land in:

```
runs/shot_30201/
  inputs/
    execution_authority/
  contracts/
  synthetic/
  metrics/
  magnetic_probes.pickle
  inverse_run.py
  forward_run.py
  manifest.json

The run folder is **execution-authoritative**: numerical settings (grid, profile knobs, boundary constraints, solver tolerances)
are declared explicitly in:

```
runs/shot_<N>/inputs/execution_authority/execution_authority_bundle.json
```

Generated `inverse_run.py` / `forward_run.py` fail-fast if this bundle is missing.
```

---

## 6. End-to-End Reconstruction (with execution + scoring)

To execute FreeGSNKE and score residuals using diagnostic contracts:

```bash
mast-freegsnke run \
  --shot 30201 \
  --config configs/config.example.json \
  --machine machine_configs/MAST \
  --execute-freegsnke --freegsnke-mode both \
  --enable-contract-metrics \
  --contracts configs/diagnostic_contracts.example.json \
  --coil-map configs/coil_map.example.json
```

If FreeGSNKE lives in a different Python environment:

```bash
mast-freegsnke run \
  --shot 30201 \
  --config configs/config.example.json \
  --machine machine_configs/MAST \
  --execute-freegsnke --freegsnke-mode both \
  --freegsnke-python /path/to/freegsnke/python
```

Execution logs are captured in:

```
runs/shot_<N>/logs/
```

Internal solver-state evidence is emitted after successful FreeGSNKE runs:

```
runs/shot_<N>/solver_introspection/
  solver_state_snapshot.json
  DEFAULT_DETECTION_REPORT.json
  numerics_trace.json
```

The execution authority bundle now includes explicit profile basis governance:

- `inputs/execution_authority/profile_basis_authority.json`
- `execution_authority_bundle.json` → `profile_basis`

This prevents silent changes to FreeGSNKE's implicit profile representation from going unnoticed.

---

## 7. Diagnostic Contracts Authority

Contracts define **exactly** what is compared:

- experimental CSV location + columns
- synthetic CSV location + columns
- sign/scale conventions
- interpolation onto a common timebase

Validate contracts:

```bash
mast-freegsnke contracts-validate --contracts configs/diagnostic_contracts.example.json
```

---

## 8. Coil Mapping Authority

Coil mapping defines a strict, auditable mapping from experimental PF-current columns to FreeGSNKE coil identifiers.

Validate:

```bash
mast-freegsnke coilmap-validate --coil-map configs/coil_map.example.json
```

---

## 9. Magnetic Probe Geometry Requirements (Issue #207)

FAIR-MAST provides magnetic signals but does **not** provide the full metrology required by FreeGSNKE synthetic diagnostics.

You must supply probe geometry via the machine directory using one of:

1) `probe_geometry.json` (preferred)
2) a Python module exporting geometry
3) `flux_loops.csv` / `pickup_coils.csv`

Generate templates:

```bash
mast-freegsnke geom-template --machine machine_configs/MAST
```

Validate geometry:

```bash
mast-freegsnke geom-validate --machine machine_configs/MAST
mast-freegsnke geom-smoke --machine machine_configs/MAST
```

The pipeline emits `magnetic_probes.pickle` in a FreeGSNKE-native dict format.

---

## 10. Reproducibility & Determinism

- Frozen stage ordering.
- Explicit precedence:
  - window override > consensus > single-signal
  - geometry sources resolved deterministically
- All stage outcomes recorded in `manifest.json`.
- No hidden iteration or implicit optimization.

---

## 11. Examples

See the `examples/` directory for progressive, runnable walkthroughs:

- `01_basic_shot_download/`
- `02_window_inference/`
- `03_geometry_validation/`
- `04_full_reconstruction_no_execution/`
- `05_full_reconstruction_with_execution/`
- `06_contract_driven_scoring/`

---

## 12. Troubleshooting

- **`s5cmd` not found**: ensure `s5cmd` is on PATH.
- **FreeGSNKE not installed**: run with `--execute-freegsnke` disabled or provide `--freegsnke-python`.
- **Synthetic diagnostics crash**: geometry is incomplete; run `geom-validate` and fix missing fields.

---

## 13. Versioning & Citation

- Package version: **1.2.0**
- Please cite the repository and include `manifest.json` + contracts + geometry reports in any derived publications.
## Machine Authority (v2.0)

For reviewer-grade runs, this project supports a **versioned machine authority bundle** under `machine_authority/`.
The authority is **snapshotted** into each run folder (`runs/shot_<N>/machine_authority_snapshot/`) and hashed.

Minimum required files:

- `machine_authority/authority_manifest.json`
- `machine_authority/probe_geometry.json`
- `machine_authority/coil_geometry.json`
- `machine_authority/diagnostic_registry.json`

Validate:

```bash
mast-freegsnke machine-validate --machine-authority machine_authority/
```

> Note: the shipped `machine_authority/` is a **template**. Populate it from an authoritative MAST/FreeGSNKE machine
definition repository. This pipeline will not invent metrology.

## Reproducibility Lock & Manifest v2 (v2.0)

Each successful (or failed) run writes:

- `runs/shot_<N>/provenance/file_hashes.json` (SHA256 of run artifacts)
- `runs/shot_<N>/provenance/env_fingerprint.json` (Python/OS fingerprint)
- `runs/shot_<N>/provenance/requirements.freeze.json` (`pip freeze`)
- `runs/shot_<N>/provenance/repo_state.json` (git commit if available)
- `runs/shot_<N>/provenance/manifest_v2.json` (hash-based run manifest)

Optional (can be expensive): hash the downloaded cache tree by setting `provenance_hash_data: true` in config.

## Reviewer Pack (v2.0)

To export a self-contained run bundle for collaborators/reviewers:

```bash
mast-freegsnke reviewer-pack --run runs/shot_30201
```

This creates `runs/shot_30201/REVIEWER_PACK/` with:
manifest(s), provenance, machine authority snapshot, contracts, metrics, plots (if available), and logs.


# v3.0.0 — Robustness & Sensitivity Authority

New CLI Commands:

    mast-freegsnke robustness-run
    mast-freegsnke robustness-pack

Capabilities:
- Deterministic DOE scenario generation
- Explicit robust selection policies (maximin, quantile)
- Stability tier classification (GREEN/YELLOW/RED)
- Hash-lockable scenario descriptors
- Reviewer-grade robustness export


# v4.0.0 — Regime-Segmented Robustness & Continuity Authority

New CLI Commands:

    mast-freegsnke robustness-run --run runs/shot_<N>
    mast-freegsnke robustness-pack --run runs/shot_<N>

What it does:
- Deterministically generates a multi-window library around the baseline window
- Executes deterministic DOE scenarios per window (window clipping, leave-one-out, contract scale perturbations)
- Aggregates metrics per window and selects a robust choice with deterministic tie-breaking
- Computes stability tiers (GREEN/YELLOW/RED) from relative degradation across scenarios
- Computes cross-window continuity metrics and a global robust choice
- Exports a robustness reviewer pack as a self-contained evidence bundle


## v4.1.0 — Phase Consistency + Attribution + Plot Authority

Adds licensing-style robustness evidence on top of v4.0.0:

- Phase-consistency classification (PHASE-CONSISTENT / PHASE-DRIFTING / PHASE-BREAKING)
- Sensitivity attribution ledger (dominant scenario families, top damage scenarios)
- Deterministic plot generation with hash manifest (`plots_manifest.json`)
- Robustness reviewer pack upgraded to include new evidence outputs

CLI is unchanged:

```bash
mast-freegsnke robustness-run --run runs/shot_<N>
mast-freegsnke robustness-pack --run runs/shot_<N>
```


## v5.0.0 — Cross-Shot Robustness Atlas + Certified Comparator

New CLI commands:

- `mast-freegsnke corpus-build --runs <run_dirs...> --out <corpus_dir>`
- `mast-freegsnke atlas-build --corpus <corpus_dir>`
- `mast-freegsnke compare-run --A <atlasA> --B <atlasB> --out <compare_dir>`
- `mast-freegsnke regression-guard --delta <compare_dir>/delta_scorecards.json --out <path>`

These commands provide deterministic cross-shot aggregation and A/B certified deltas without hidden optimization.


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


## Logs
Each launcher writes a full console transcript to `logs/run_<timestamp>.log`.

- Windows: logging uses PowerShell `Start-Transcript` (no piping), so interactive prompts reliably accept keyboard input.
- Linux/macOS: stdout/stderr are mirrored to the log via `tee`.

Each run also captures `logs/pip_freeze_<timestamp>.txt` for reproducibility.

### Interactive prompts
- Required fields (e.g. shot number) **reprompt until valid** (digits only) or you quit with `q`.
- If you launch `run_pipeline.cmd` by double-click, the window will stay open on error so you can read the message.
  - Set `RUN_PIPELINE_NO_PAUSE=1` to disable this behavior.


### Windows interactive prompt robustness
The Windows launcher escapes parentheses in prompt strings to avoid `cmd.exe` parser errors (e.g. `. was unexpected at this time.`). If you previously saw the launcher terminate after entering a shot number, update to v10.0.3+.


### Windows interactive runner note
On Windows, interactive prompts are handled by a Python helper (`python -m mast_freegsnke.interactive_run`) to avoid cmd.exe parsing edge-cases while preserving full transcript logging.
