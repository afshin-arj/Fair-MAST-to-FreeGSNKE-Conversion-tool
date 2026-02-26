from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

DEFAULT_PF_RULES = {
  "P2_inner": {"include": ["p2", "inner"], "exclude": ["outer"]},
  "P2_outer": {"include": ["p2", "outer"], "exclude": ["inner"]},
  "P3": {"include": ["p3"], "exclude": []},
  "P4": {"include": ["p4"], "exclude": []},
  "P5": {"include": ["p5"], "exclude": []},
  "P6": {"include": ["p6"], "exclude": []},
  "Solenoid": {"include": ["sol"], "exclude": []}
}

MAP_HELPER = "#!/usr/bin/env python3\n# Auto-map pf_active_raw.csv -> pf_currents.csv.\n#\n# Behavior:\n# - Uses pf_map_rules.json if present and non-empty.\n# - If rules are missing/empty, auto-suggests mapping by scoring column-name tokens.\n#\n# Author: \u00a9 2026 Afshin Arjhangmehr\n\nfrom __future__ import annotations\nfrom pathlib import Path\nimport json\nimport numpy as np\nimport pandas as pd\nfrom typing import Dict, List, Tuple\n\nHERE = Path(__file__).resolve().parent\nINPUTS = HERE / \"inputs\"\nRAW = INPUTS / \"pf_active_raw.csv\"\nOUT = INPUTS / \"pf_currents.csv\"\nRULES = HERE / \"pf_map_rules.json\"\n\nDEFAULT_CIRCUITS = [\"P2_inner\",\"P2_outer\",\"P3\",\"P4\",\"P5\",\"P6\",\"Solenoid\"]\n\ndef norm(s: str) -> str:\n    return ''.join(ch.lower() if ch.isalnum() else ' ' for ch in s)\n\ndef tokenize(s: str) -> List[str]:\n    return [t for t in norm(s).split() if t]\n\ndef score(col_tokens: List[str], include: List[str], exclude: List[str]) -> float:\n    inc = sum(1.0 for t in include if t in col_tokens)\n    exc = sum(2.0 for t in exclude if t in col_tokens)\n    return inc - exc\n\ndef best_matches(columns: List[str], include: List[str], exclude: List[str], k: int = 3) -> List[Tuple[str,float]]:\n    scored = []\n    for c in columns:\n        sc = score(tokenize(c), include, exclude)\n        if sc > 0:\n            scored.append((c, sc))\n    scored.sort(key=lambda x: (-x[1], x[0]))\n    return scored[:k]\n\ndef auto_rules(_columns: List[str]) -> Dict[str, Dict[str, List[str]]]:\n    return {\n        \"P2_inner\": {\"include\": [\"p2\",\"inner\"], \"exclude\": [\"outer\"]},\n        \"P2_outer\": {\"include\": [\"p2\",\"outer\"], \"exclude\": [\"inner\"]},\n        \"P3\": {\"include\": [\"p3\"], \"exclude\": []},\n        \"P4\": {\"include\": [\"p4\"], \"exclude\": []},\n        \"P5\": {\"include\": [\"p5\"], \"exclude\": []},\n        \"P6\": {\"include\": [\"p6\"], \"exclude\": []},\n        \"Solenoid\": {\"include\": [\"sol\",\"cs\",\"oh\"], \"exclude\": []},\n    }\n\ndef load_rules() -> Dict[str, Dict[str, List[str]]]:\n    if not RULES.exists():\n        return {}\n    try:\n        obj = json.loads(RULES.read_text())\n        if isinstance(obj, dict) and len(obj) > 0:\n            return obj\n    except Exception:\n        return {}\n    return {}\n\ndef pick_columns(columns: List[str], include_tokens: List[str], exclude_tokens: List[str]) -> List[str]:\n    chosen = []\n    for c in columns:\n        cn = norm(c)\n        if all(tok in cn for tok in include_tokens) and not any(tok in cn for tok in exclude_tokens):\n            chosen.append(c)\n    return chosen\n\ndef main() -> None:\n    if not RAW.exists():\n        raise FileNotFoundError(f\"Missing input: {RAW}\")\n\n    df = pd.read_csv(RAW)\n    cols = [c for c in df.columns if c != \"time\"]\n\n    rules = load_rules()\n    if not rules:\n        rules = auto_rules(cols)\n        RULES.write_text(json.dumps(rules, indent=2) + \"\\n\")\n        print(f\"[INFO] Wrote auto rules to {RULES}\")\n\n        print(\"[INFO] Top suggestions per circuit (edit pf_map_rules.json if wrong):\")\n        for circuit, spec in rules.items():\n            sug = best_matches(cols, [t.lower() for t in spec.get(\"include\",[])], [t.lower() for t in spec.get(\"exclude\",[])], k=3)\n            print(f\"  {circuit:9s}: {sug}\")\n\n    out = pd.DataFrame({\"time\": df[\"time\"].to_numpy(dtype=float)})\n    report = {}\n    for circuit in DEFAULT_CIRCUITS:\n        spec = rules.get(circuit, {\"include\": [], \"exclude\": []})\n        inc = [t.lower() for t in spec.get(\"include\", [])]\n        exc = [t.lower() for t in spec.get(\"exclude\", [])]\n        matched = pick_columns(cols, inc, exc)\n        report[circuit] = matched\n\n        if len(matched) == 0:\n            out[circuit] = np.nan\n        elif len(matched) == 1:\n            out[circuit] = df[matched[0]].to_numpy(dtype=float)\n        else:\n            out[circuit] = df[matched].to_numpy(dtype=float).mean(axis=1)\n\n    out.to_csv(OUT, index=False)\n    print(\"[OK] Wrote:\", OUT)\n    print(\"Mapping report:\")\n    for k, v in report.items():\n        print(f\"  {k:9s}: {v}\")\n\nif __name__ == \"__main__\":\n    main()\n"

@dataclass
class ScriptGenerator:
    templates_dir: Path

    def generate(self, run_dir: Path, machine_dir: Path, formed_frac: float) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir/"inputs").mkdir(parents=True, exist_ok=True)

        inv_tpl = (self.templates_dir/"inverse_run.py.tpl").read_text()
        fwd_tpl = (self.templates_dir/"forward_run.py.tpl").read_text()

        (run_dir/"inverse_run.py").write_text(inv_tpl.format(machine_dir=str(machine_dir), formed_frac=formed_frac))
        (run_dir/"forward_run.py").write_text(fwd_tpl.format(machine_dir=str(machine_dir)))

        (run_dir/"pf_map_rules.json").write_text(json.dumps(DEFAULT_PF_RULES, indent=2) + "\n")
        (run_dir/"map_pf_currents.py").write_text(MAP_HELPER)

        (run_dir/"HOW_TO_RUN.txt").write_text(self._howto(machine_dir))

        try:
            (run_dir/"inverse_run.py").chmod(0o755)
            (run_dir/"forward_run.py").chmod(0o755)
            (run_dir/"map_pf_currents.py").chmod(0o755)
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
            "2) Map PF currents (recommended):\n"
            "     python map_pf_currents.py\n"
            "   Edit pf_map_rules.json if mapping is wrong.\n\n"
            "3) Machine stub for committing (optional):\n"
            "     cat machine_stub_freegsnke.py\n\n"
            "4) Run inverse solve:\n"
            "     python inverse_run.py\n\n"
            "5) Run forward replay:\n"
            "     python forward_run.py\n"
        ).format(machine_dir=machine_dir)
