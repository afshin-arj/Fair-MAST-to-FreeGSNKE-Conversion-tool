# Example 13 — v8.0.0 Truth-by-Replay + Forensics

## 1) Replay / verify a run directory (strict env closure)

```bash
mast-freegsnke replay-run --target runs/shot_<N> --mode strict
```

Outputs in:
- `runs/shot_<N>/replay/REPLAY_REPORT.json`
- `runs/shot_<N>/replay/REPLAY_REPORT.md`

## 2) Replay / verify an exported pack (relaxed env closure)

```bash
mast-freegsnke replay-run --target runs/shot_<N>/CONSISTENCY_TRIANGLE_REVIEWER_PACK --mode relaxed
```

## 3) Forensic compare two runs/packs

```bash
mast-freegsnke forensic-compare --A runs/shot_<A> --B runs/shot_<B> --out forensics_AB
```

Writes:
- `forensics_AB/FORENSIC_DELTA.json`
- `forensics_AB/FORENSIC_DELTA.md`

## 4) Non-determinism sentinel

```bash
mast-freegsnke nondeterminism-check --target runs/shot_<N> --n 3
```
