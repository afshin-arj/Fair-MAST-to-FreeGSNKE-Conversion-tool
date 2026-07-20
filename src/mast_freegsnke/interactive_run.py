"""Interactive launcher: shot number(s) only; all other knobs from config.

Author: © 2026 Afshin Arjhangmehr
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List, Optional

from . import cli
from .batch import run_shot_batch
from .config import AppConfig
from .contracts_status import contract_metrics_status_line, diagnostic_calibration_status_line
from .shot_suitability import assess_shot_suitability, format_unsuitable_message


_SHOT_TOKEN = re.compile(r"^[0-9]+$")


def parse_shot_list(raw: str) -> List[int]:
    """Parse one or more shot numbers from a single prompt line.

    Accepts space- and/or comma-separated digits, e.g.:
      30201
      30201 30202
      30201,30202
      30201, 30202 30400
    """
    parts = [p for p in re.split(r"[\s,]+", raw.strip()) if p]
    if not parts:
        raise ValueError("empty")
    shots: List[int] = []
    seen: set[int] = set()
    for p in parts:
        if not _SHOT_TOKEN.fullmatch(p):
            raise ValueError(p)
        n = int(p)
        if n not in seen:
            seen.add(n)
            shots.append(n)
    return shots


def _prompt_shot_list(msg: str) -> List[int]:
    while True:
        s = input(msg).strip()
        if s.lower() == "q":
            raise SystemExit(0)
        if not s:
            print("[WARN] Value is required.")
            continue
        try:
            return parse_shot_list(s)
        except ValueError as e:
            bad = str(e)
            if bad == "empty":
                print("[WARN] Value is required.")
            else:
                print(f"[WARN] Invalid token {bad!r}; use digits only (e.g. 30201 30202).")


def filter_suitable_shots(
    cfg: AppConfig,
    shots: List[int],
    *,
    interactive_reprompt: bool = False,
) -> List[int]:
    """Return suitable shots; print professional skip messages for others.

    When ``interactive_reprompt`` is True and the queue becomes empty (all
    unsuitable, or a lone unsuitable shot), re-prompt until at least one
    suitable shot is entered (or the user quits with ``q``).
    """
    while True:
        suitable: List[int] = []
        for shot in shots:
            if not bool(getattr(cfg, "enable_shot_suitability_gate", True)):
                suitable.append(shot)
                continue
            rep = assess_shot_suitability(cfg, shot)
            if rep.suitable:
                suitable.append(shot)
                continue
            print(format_unsuitable_message(rep))
            if len(shots) == 1:
                print(
                    "[INFO] Please enter a different MAST shot number "
                    "(or 'q' to quit)."
                )
            else:
                print(
                    f"[SKIP] Shot {shot} is not suitable — continuing with "
                    "the remaining shot(s) in this queue."
                )
        if suitable:
            return suitable
        if not interactive_reprompt:
            return []
        print("")
        print(
            "[INFO] None of the entered shots are suitable for analysis. "
            "Please try other shot number(s)."
        )
        shots = _prompt_shot_list(
            "Enter MAST shot number(s) (digits; space/comma separated; 'q' to quit): "
        )


def _preflight_shot_only(cfg: AppConfig, cwd: Path) -> Optional[str]:
    """Return a fail message if download/FreeGSNKE defaults cannot run; else None."""
    from .preflight import collect_happy_path_failures

    fails = collect_happy_path_failures(cfg, cwd)
    if not fails:
        return None
    return "\n".join(fails)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="mast-freegsnke-interactive")
    ap.add_argument("--default-config", default="configs/default.json")
    ns = ap.parse_args(argv)

    print("")
    print("===========================================================================")
    print("Interactive Run (shot-only)")
    print("===========================================================================")
    print("")

    config_path = Path(ns.default_config)
    if not config_path.exists():
        print(f"[FAIL] Config file not found: {config_path}")
        print("[HINT] Use configs/default.json (shipped) or pass --default-config <path>.")
        return 2

    cwd = Path.cwd()
    cfg = AppConfig.load(config_path)
    print(f"[INFO] Using config: {config_path}")
    print(f"[INFO] runs_dir={cfg.runs_dir}  (outputs → {cfg.runs_dir}/<shot>)")
    print(f"[INFO] execute_freegsnke={cfg.execute_freegsnke} mode={cfg.freegsnke_run_mode}")
    print(f"[INFO] machine_authority_dir={cfg.machine_authority_dir}")
    print(f"[INFO] coil_map_path={cfg.coil_map_path}")
    print(f"[INFO] enable_contract_metrics={cfg.enable_contract_metrics}")
    print(
        f"[INFO] enable_shot_suitability_gate="
        f"{getattr(cfg, 'enable_shot_suitability_gate', True)}"
    )
    status_line = contract_metrics_status_line(cfg)
    if status_line:
        print(status_line)
    print(diagnostic_calibration_status_line(cfg, cwd=config_path.parent if config_path.is_absolute() else cwd))

    pre = _preflight_shot_only(cfg, cwd)
    if pre:
        print(f"[FAIL] {pre}")
        return 2
    print("[OK] preflight: s5cmd + FreeGSNKE python ready")
    print("")

    requested = _prompt_shot_list(
        "Enter MAST shot number(s) (digits; space/comma separated; 'q' to quit): "
    )
    shots = filter_suitable_shots(cfg, requested, interactive_reprompt=True)
    print(f"[INFO] Shots queued for analysis: {', '.join(str(s) for s in shots)}")

    def _run_one(shot: int) -> int:
        return cli.main(["run", "--config", str(config_path), "--shot", str(shot)])

    # Suitability already applied interactively; batch runs the filtered list.
    return run_shot_batch(
        shots,
        _run_one,
        runs_dir=cfg.runs_dir,
        abort_on_failure=cfg.batch_abort_on_failure,
        describe=lambda shot: f"mast-freegsnke run --config {config_path} --shot {shot}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
