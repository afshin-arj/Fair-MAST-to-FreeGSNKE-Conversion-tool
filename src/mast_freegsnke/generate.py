from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

# Suggest-only helper (NOT used in the happy path). Prints token suggestions;
# never writes production pf_currents.csv unless --write is passed explicitly
# by a developer (not invoked by the pipeline).
SUGGEST_PF_HELPER = '''#!/usr/bin/env python3
# Suggest-only PF column mapping helper (NOT an authority).
# Production mapping must use coil_map JSON applied by the pipeline.
#
# Author: © 2026 Afshin Arjhangmehr

from __future__ import annotations
from pathlib import Path
import json
import pandas as pd
from typing import Dict, List, Tuple

HERE = Path(__file__).resolve().parent
INPUTS = HERE / "inputs"
RAW = INPUTS / "pf_active_raw.csv"

DEFAULT_CIRCUITS = ["P2_inner","P2_outer","P3","P4","P5","P6","Solenoid"]

def norm(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else " " for ch in s)

def tokenize(s: str) -> List[str]:
    return [t for t in norm(s).split() if t]

def score(col_tokens: List[str], include: List[str], exclude: List[str]) -> float:
    inc = sum(1.0 for t in include if t in col_tokens)
    exc = sum(2.0 for t in exclude if t in col_tokens)
    return inc - exc

def best_matches(columns: List[str], include: List[str], exclude: List[str], k: int = 3) -> List[Tuple[str,float]]:
    scored = []
    for c in columns:
        sc = score(tokenize(c), include, exclude)
        if sc > 0:
            scored.append((c, sc))
    scored.sort(key=lambda x: (-x[1], x[0]))
    return scored[:k]

def main() -> None:
    if not RAW.exists():
        raise FileNotFoundError(f"Missing input: {RAW}")
    df = pd.read_csv(RAW)
    cols = [c for c in df.columns if c != "time"]
    rules = {
        "P2_inner": {"include": ["p2","inner"], "exclude": ["outer"]},
        "P2_outer": {"include": ["p2","outer"], "exclude": ["inner"]},
        "P3": {"include": ["p3"], "exclude": []},
        "P4": {"include": ["p4"], "exclude": []},
        "P5": {"include": ["p5"], "exclude": []},
        "P6": {"include": ["p6"], "exclude": []},
        "Solenoid": {"include": ["sol","cs","oh"], "exclude": []},
    }
    print("[SUGGEST-ONLY] Proposed coil_map.mapping entries (edit & save as authority JSON):")
    mapping = {}
    for circuit, spec in rules.items():
        sug = best_matches(cols, [t.lower() for t in spec["include"]], [t.lower() for t in spec["exclude"]], k=1)
        print(f"  {circuit:9s}: {sug}")
        if sug:
            mapping[sug[0][0]] = {"coil": circuit, "scale": 1.0, "sign": 1}
    print(json.dumps({"version": "1.0", "mapping": mapping}, indent=2))
    print("[HINT] Save to configs/coil_map.json and set coil_map_path in config. Do NOT run heuristic writers in production.")

if __name__ == "__main__":
    main()
'''


@dataclass
class ScriptGenerator:
    templates_dir: Path

    def _render_template(self, template: str, *, machine_dir: Path, formed_frac: float | None = None) -> str:
        """Render code templates safely (no str.format collisions).

        Templates must use literal tokens:
          - __MACHINE_DIR_REPR__
          - __FORMED_FRAC__ (optional)

        This avoids accidental interpretation of Python braces (dicts, f-strings) by str.format().
        """
        out = template.replace("__MACHINE_DIR_REPR__", repr(str(machine_dir)))
        if "__FORMED_FRAC__" in out:
            if formed_frac is None:
                raise ValueError("Template requires __FORMED_FRAC__ but formed_frac is None")
            out = out.replace("__FORMED_FRAC__", str(float(formed_frac)))
        # Guardrail: refuse unreplaced tokens
        if "__MACHINE_DIR_REPR__" in out or "__FORMED_FRAC__" in out:
            raise ValueError("Unreplaced template tokens remain in rendered script")
        return out

    def generate(self, run_dir: Path, machine_dir: Path, formed_frac: float) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir/"inputs").mkdir(parents=True, exist_ok=True)

        inv_tpl = (self.templates_dir/"inverse_run.py.tpl").read_text()
        fwd_tpl = (self.templates_dir/"forward_run.py.tpl").read_text()

        (run_dir/"inverse_run.py").write_text(self._render_template(inv_tpl, machine_dir=machine_dir, formed_frac=formed_frac))
        (run_dir/"forward_run.py").write_text(self._render_template(fwd_tpl, machine_dir=machine_dir))

        # Suggest-only helper (never applied automatically).
        (run_dir/"suggest_pf_map.py").write_text(SUGGEST_PF_HELPER)

        (run_dir/"HOW_TO_RUN.txt").write_text(self._howto(machine_dir))

        try:
            (run_dir/"inverse_run.py").chmod(0o755)
            (run_dir/"forward_run.py").chmod(0o755)
            (run_dir/"suggest_pf_map.py").chmod(0o755)
        except Exception:
            pass

    def _howto(self, machine_dir: Path) -> str:
        return (
            "HOW TO RUN (generated run folder)\n"
            "===============================\n\n"
            f"Machine directory: {machine_dir}\n\n"
            "0) Optional: check required data availability:\n"
            "     mast-freegsnke check --shot <SHOT> --config <CFG>\n\n"
            "1) Review inferred formed-plasma time window:\n"
            "     cat inputs/window.json\n\n"
            "1.5) Review execution-state authority (NO hidden defaults):\n"
            "     cat inputs/execution_authority/execution_authority_bundle.json\n"
            "   Edit it if you want to change grid, profiles, boundary constraints, or solver tolerances.\n\n"
            "2) PF currents must come from coil_map authority (pipeline stage apply_coil_map).\n"
            "   Optional suggest-only helper (does NOT write production CSVs):\n"
            "     python suggest_pf_map.py\n\n"
            "3) Machine stub for committing (optional):\n"
            "     cat machine_stub_freegsnke.py\n\n"
            "4) Run inverse solve:\n"
            "     python inverse_run.py\n\n"
            "5) Run forward replay:\n"
            "     python forward_run.py\n"
        )
