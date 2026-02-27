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


PY_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PY_BIN="python"
else
  echo "[FAIL] Python not found. Install Python 3.9+ and retry." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "[INFO] Creating virtual environment: .venv"
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

DEFAULT_CONFIG="configs/config.example.json"
DEFAULT_MACHINE="machine_configs/MAST"
DEFAULT_CONTRACTS="configs/diagnostic_contracts.example.json"
DEFAULT_COILMAP="configs/coil_map.example.json"

echo
read -r -p "Config path [$DEFAULT_CONFIG]: " CFG
CFG="${CFG:-$DEFAULT_CONFIG}"

echo
echo "[STEP] Environment doctor"
python -m mast_freegsnke.cli doctor --config "$CFG" || true

echo
while true; do
  echo
  read -r -p "Shot number (required, digits; 'q' to quit): " SHOT
  if [[ "${SHOT,,}" == "q" ]]; then
    echo "[INFO] User quit."
    exit 2
  fi
  if [[ -z "${SHOT}" ]]; then
    echo "[WARN] Shot number is required." >&2
    continue
  fi
  if [[ ! "${SHOT}" =~ ^[0-9]+$ ]]; then
    echo "[WARN] Shot must be digits only (e.g., 30201)." >&2
    continue
  fi
  break
done

read -r -p "Machine directory [$DEFAULT_MACHINE]: " MACH
MACH="${MACH:-$DEFAULT_MACHINE}"

read -r -p "Window override tstart [s] (blank = auto): " TSTART
read -r -p "Window override tend [s] (blank = auto): " TEND

EXEC_FLAG=""
MODE_FLAG=""
FGPY_FLAG=""
read -r -p "Execute FreeGSNKE now? (y/N): " EXE
if [[ "${EXE,,}" == "y" ]]; then
  EXEC_FLAG="--execute-freegsnke"
  read -r -p "FreeGSNKE mode [both|inverse|forward] (default both): " MODE
  MODE="${MODE:-both}"
  MODE_FLAG="--freegsnke-mode ${MODE}"
  read -r -p "Optional: path to FreeGSNKE python exe (blank = use config): " FGPY
  if [[ -n "$FGPY" ]]; then
    FGPY_FLAG="--freegsnke-python ${FGPY}"
  fi
fi

MET_FLAG=""
CONTRACTS_FLAG=""
COILMAP_FLAG=""
read -r -p "Enable contract metrics? (y/N): " MET
if [[ "${MET,,}" == "y" ]]; then
  MET_FLAG="--enable-contract-metrics"
  read -r -p "Contracts JSON [$DEFAULT_CONTRACTS]: " CONTRACTS
  CONTRACTS="${CONTRACTS:-$DEFAULT_CONTRACTS}"
  read -r -p "Coil-map JSON [$DEFAULT_COILMAP]: " COILMAP
  COILMAP="${COILMAP:-$DEFAULT_COILMAP}"
  CONTRACTS_FLAG="--contracts ${CONTRACTS}"
  COILMAP_FLAG="--coil-map ${COILMAP}"
fi

TSTART_FLAG=""
TEND_FLAG=""
if [[ -n "$TSTART" ]]; then TSTART_FLAG="--tstart ${TSTART}"; fi
if [[ -n "$TEND" ]]; then TEND_FLAG="--tend ${TEND}"; fi

echo
echo "[RUN] mast-freegsnke run --shot ${SHOT} --config ${CFG} --machine ${MACH} ${TSTART_FLAG} ${TEND_FLAG} ${EXEC_FLAG} ${MODE_FLAG} ${FGPY_FLAG} ${MET_FLAG} ${CONTRACTS_FLAG} ${COILMAP_FLAG}"
echo

python -m mast_freegsnke.cli run \
  --shot "${SHOT}" \
  --config "${CFG}" \
  --machine "${MACH}" \
  ${TSTART_FLAG} \
  ${TEND_FLAG} \
  ${EXEC_FLAG} \
  ${MODE_FLAG} \
  ${FGPY_FLAG} \
  ${MET_FLAG} \
  ${CONTRACTS_FLAG} \
  ${COILMAP_FLAG}

echo
echo "[OK] Completed. See runs/shot_${SHOT}/"
