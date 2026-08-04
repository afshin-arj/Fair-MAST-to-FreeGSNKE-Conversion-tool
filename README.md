# Fair-MAST → FreeGSNKE

**Enter a MAST shot number. Everything else is automatic.**

Classic MAST FAIR-MAST Level-2 data → FreeGSNKE equilibrium reconstruction → residuals, plots, and hashed provenance under `SHOT/<N>/`.

<p align="center">
  <img src="docs/assets/readme-hero-pipeline.png" alt="FAIR-MAST Level-2 to FreeGSNKE to SHOT pack pipeline" width="920"/>
</p>

| | |
|---|---|
| **Version** | **11.34.2** |
| **Machine** | Classic MAST (not MAST-U) |
| **Solver** | [FreeGSNKE](https://github.com/FusionComputingLab/freegsnke) only |
| **EFIT** | Archive compare ([ADR-002](docs/adr/002-fairmast-efit-compare.md)) — not live EFIT++ |
| **Manual** | **[User Manual](docs/USER_MANUAL.md)** — install, stages, authorities, CLI |

---

## Quick start

**Windows**

```bat
git clone https://github.com/afshin-arj/Fair-MAST-to-FreeGSNKE-Conversion-tool.git
cd Fair-MAST-to-FreeGSNKE-Conversion-tool
setup_fresh.cmd
run_pipeline.cmd
run_ui.cmd
```

**Linux / macOS**

```bash
git clone https://github.com/afshin-arj/Fair-MAST-to-FreeGSNKE-Conversion-tool.git
cd Fair-MAST-to-FreeGSNKE-Conversion-tool
chmod +x setup_fresh.sh run_pipeline.sh
./setup_fresh.sh
./run_pipeline.sh
```

Requires **Python 3.11**. Happy path prompts **only** for the shot number.

```bash
mast-freegsnke doctor --config configs/default.json
mast-freegsnke run --shot 30201 --config configs/default.json
mast-freegsnke ui --config configs/default.json
```

---

## What you get

<p align="center">
  <img src="docs/assets/readme-shot-pack.png" alt="SHOT pack folder layout" width="720"/>
</p>

```text
SHOT/<N>/
├── 00_START_HERE.txt
├── 01_summary/          SUMMARY · science audit
├── 02_measured_data/    Level-2 CSV + plots
├── 03_reconstruction/   metrics · GIFs · evolutive
├── 04_efit_compare/     vs EFIT++ archive
├── 06_authorities/      snapshotted JSON + hashes
├── 07_planner/          optional GSPulse-method planner
├── 08_gsfit/            GSFit live peer (often awaiting)
└── manifest.json
```

| Stage | Role |
|-------|------|
| **Inverse** | Static GS with declared shape targets |
| **Forward** | Dump-current t0 + measured PF window; live LCFS |
| **Evolutive** | nlstepper from Inverse IC + voltages; soft-stop honesty |
| **EFIT compare** | FreeGSNKE vs archived FAIR-MAST EFIT++ |
| **Planner** | Python GSPulse-method path (ADR-004); passives blocked until cited ρ |

---

## Design laws

- **Deterministic** — no hidden smoothing or silent conventions  
- **Explicit authority** — coil map, voltage map, machine, contracts are declared JSON (hashed)  
- **Fail fast** — missing authority **blocks**; never invent metrology  
- **Manifest everything** — every stage outcome is recorded  

Browser UI: `run_ui.cmd` → `http://127.0.0.1:8050`

---

## Honest limits

- Classic MAST only · no FreeGSNKE passives until cited ρ ([ADR-005](docs/adr/005-classic-mast-passive-resistivity.md))  
- P3/P6 use declared `I×R` ohmic drive when public PF V is absent  
- EFIT tab = archive compare, not a live reconstruction engine ([ADR-003](docs/adr/003-reject-pyefit-windows-path.md))  
- GSFit = live peer scaffold ([ADR-006](docs/adr/006-gsfit-live-peer.md)); soft-skips until calib + Green’s cited  

---

## Documentation

| Document | Purpose |
|----------|---------|
| **[User Manual](docs/USER_MANUAL.md)** | Full guide — install, pipeline depth, authorities, CLI, troubleshooting |
| [HOW_TO_RUN.txt](HOW_TO_RUN.txt) | Launcher cheat sheet |
| [AGENTS.md](AGENTS.md) | North star + agent roles |
| [docs/adr/](docs/adr/README.md) | Architecture Decision Records |
| [FAIR-MAST](https://github.com/ukaea/fair-mast) · [mastapp L2](https://mastapp.site/level2-data.html) | Upstream data |

© 2026 Afshin Arjhangmehr
