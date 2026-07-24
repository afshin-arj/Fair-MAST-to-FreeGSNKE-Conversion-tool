#!/usr/bin/env bash
# Fresh-machine bootstrap for Fair-MAST → FreeGSNKE (Linux / macOS)
# Requires Python 3.11 (FreeGSNKE / scipy wheels).
set -euo pipefail
cd "$(dirname "$0")"

echo "[INFO] Fair-MAST → FreeGSNKE fresh setup"
echo "[INFO] PWD: $(pwd)"

PY_BOOT=""
if command -v python3.11 >/dev/null 2>&1; then
  PY_BOOT="python3.11"
elif command -v python3 >/dev/null 2>&1; then
  if python3 -c 'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) else 1)'; then
    PY_BOOT="python3"
  fi
elif command -v python >/dev/null 2>&1; then
  if python -c 'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) else 1)'; then
    PY_BOOT="python"
  fi
fi

if [[ -z "$PY_BOOT" ]]; then
  echo "[FAIL] Python 3.11 is required (FreeGSNKE / scipy wheels)."
  echo "       Install python3.11 (apt/brew/pyenv) and retry."
  exit 1
fi

echo "[INFO] Using: $PY_BOOT ($("$PY_BOOT" -V 2>&1))"

if [[ ! -x .venv/bin/python ]]; then
  if [[ -d .venv ]]; then
    echo "[WARN] .venv exists but bin/python missing — recreating"
    rm -rf .venv
  fi
  echo "[INFO] Creating .venv"
  "$PY_BOOT" -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python -c 'import sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) else 1)' || {
  echo "[FAIL] .venv is not Python 3.11. Remove .venv and re-run ./setup_fresh.sh"
  python -V
  exit 1
}

echo "[INFO] Upgrading pip + installing package (with UI + test extras)"
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt

echo "[INFO] Ensuring s5cmd (FAIR-MAST Level-2 sync)"
python scripts/ensure_s5cmd.py

echo "[INFO] Ensuring FreeGSNKE env (required by configs/default.json execute flags)"
python scripts/ensure_freegsnke_env.py

echo
echo "[OK] Fresh setup complete."
echo
echo "Next steps:"
echo "  1) mast-freegsnke doctor --config configs/default.json"
echo "  2) ./run_pipeline.sh          # or: mast-freegsnke run --shot <N> --config configs/default.json"
echo "  3) mast-freegsnke ui --config configs/default.json"
echo "     → http://127.0.0.1:8050"
echo
