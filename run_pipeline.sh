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

# Install hygiene:
#   RUN_PIPELINE_SKIP_INSTALL=1  -> skip pip upgrade+install entirely
#   otherwise reinstall only when pyproject.toml changed since the last
#   install (marker file .venv/.install_marker holds its SHA256).
if [[ "${RUN_PIPELINE_SKIP_INSTALL:-}" == "1" ]]; then
  echo "[INFO] RUN_PIPELINE_SKIP_INSTALL=1: skipping pip upgrade/install."
else
  INSTALL_MARKER=".venv/.install_marker"
  PYPROJECT_HASH="$(python -c 'import hashlib; print(hashlib.sha256(open("pyproject.toml","rb").read()).hexdigest())' 2>/dev/null || true)"
  MARKER_HASH=""
  [[ -f "$INSTALL_MARKER" ]] && MARKER_HASH="$(cat "$INSTALL_MARKER")"
  if [[ -n "$PYPROJECT_HASH" && "$MARKER_HASH" == "$PYPROJECT_HASH" ]]; then
    echo "[INFO] Install up to date (pyproject.toml unchanged); skipping reinstall."
  else
    echo "[INFO] Upgrading pip..."
    python -m pip install --upgrade pip

    echo "[INFO] Installing package (editable) with extras: zarr,dev"
    python -m pip install -e ".[zarr,dev]"
    if [[ -n "$PYPROJECT_HASH" ]]; then
      printf '%s\n' "$PYPROJECT_HASH" > "$INSTALL_MARKER"
    fi
  fi
fi

# Shot-only happy path: interactive launcher prompts for one or more shot
# numbers; every other knob comes from configs/default.json.
# Outputs land under SHOT/<shot> (e.g. SHOT/30201).
RC=0
python -m mast_freegsnke.interactive_run --default-config "configs/default.json" || RC=$?

echo
echo "[INFO] Completed with exit code ${RC}"
echo "[INFO] Shot outputs: ${REPO_ROOT}/SHOT/<shot_number>"
exit ${RC}
