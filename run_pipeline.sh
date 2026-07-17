#!/usr/bin/env bash
set -euo pipefail

# -----------------------------------------------------------------------------
# MAST -> FreeGSNKE Pipeline launcher (Linux/macOS)
# - Creates/uses .venv
# - Installs/updates package + optional extras
# - Runs interactive shot workflow
#
# Author: © 2026 Afshin Arjhangmehr
# -----------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

# Logging: capture full stdout/stderr to logs/run_<timestamp>.log while still echoing to console
mkdir -p logs
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="logs/run_${TS}.log"
exec > >(tee -a "$LOG_FILE") 2>&1
echo "[INFO] Logging to: $LOG_FILE"
echo "[INFO] Host: $(hostname 2>/dev/null || echo unknown)  OS: $(uname -a 2>/dev/null || echo unknown)"
echo "[INFO] Started: $(date -Iseconds)"

# Basic environment fingerprint (for support/debugging)
echo "[ENV] Shell: $SHELL"
echo "[ENV] PWD: $(pwd)"


# Prefer Python 3.11 when available (FAIR-MAST Zarr + FreeGSNKE stack).
PY_BIN=""
if command -v python3.11 >/dev/null 2>&1; then
  PY_BIN="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
else
  echo "[FAIL] Python not found. Install Python 3.11+ and retry." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "[INFO] Creating virtual environment: .venv (bootstrap: ${PY_BIN})"
  "$PY_BIN" -m venv .venv
fi

source .venv/bin/activate

echo "[INFO] Python:"
python -V
echo "[INFO] Pip:"
python -m pip -V

# Capture pip freeze for reproducibility
python -m pip freeze > "logs/pip_freeze_${TS}.txt"
echo "[INFO] Wrote: logs/pip_freeze_${TS}.txt"

echo "[INFO] Upgrading pip..."
python -m pip install --upgrade pip

echo "[INFO] Installing package (editable) with extras: zarr,dev"
python -m pip install -e ".[zarr,dev]"

# Shot-only happy path: interactive launcher prompts for one or more shot
# numbers; every other knob comes from configs/default.json.
# Outputs land under SHOTS/<shot> (e.g. SHOTS/30201).
RC=0
python -m mast_freegsnke.interactive_run --default-config "configs/default.json" || RC=$?

echo
echo "[INFO] Completed with exit code ${RC}"
echo "[INFO] Shot outputs: ${REPO_ROOT}/SHOTS/<shot_number>"
exit ${RC}
