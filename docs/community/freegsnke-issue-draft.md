## Introduction

Hello FreeGSNKE team — thank you for releasing and maintaining FreeGSNKE. We rely on it as the equilibrium / evolutive solver in an open MAST analysis pipeline.

We maintain a shot-only tool that takes a MAST shot number, downloads FAIR-MAST Level-2 data, resolves machine/coil/diagnostic authorities, generates FreeGSNKE inputs and scripts, and runs static inverse/forward plus evolutive forward, with residual metrics and provenance:

**Repository:** https://github.com/afshin-arj/Fair-MAST-to-FreeGSNKE-Conversion-tool

Happy path (design intent):

```text
mast-freegsnke run --shot <N>
```

The pipeline is built around FreeGSNKE (not a substitute solver on the Windows happy path). We also compare FreeGSNKE results to archived EFIT++ products published in FAIR-MAST Level-2, and keep machine/coil/diagnostic choices as explicit, hashed authorities rather than silent heuristics.

## Request — Consider listing / linking the tool

If it fits your community resources, we would be grateful if you considered mentioning or linking this repository from the FreeGSNKE GitHub README and/or project website (for example under related software, applications, or community tools). Happy to adjust packaging, docs, or citation text to match your preferences.

Thank you again for FreeGSNKE — happy to collaborate on documentation or example shots if useful.
