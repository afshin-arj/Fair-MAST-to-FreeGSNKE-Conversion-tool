@echo off
setlocal EnableExtensions

REM ---------------------------------------------------------------------------
REM Fresh-machine bootstrap for Fair-MAST → FreeGSNKE (Windows)
REM Clone the repo, run this once, then use run_pipeline.cmd / run_ui.cmd
REM Requires Python 3.11 (FreeGSNKE / scipy wheels).
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

echo [INFO] Fair-MAST → FreeGSNKE fresh setup
echo [INFO] PWD: %CD%

set "PY_BOOT="
where py >nul 2>nul
if not errorlevel 1 (
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PY_BOOT=py -3.11"
)
if "%PY_BOOT%"=="" (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY_BOOT=python"
  )
)
if "%PY_BOOT%"=="" (
  echo [FAIL] Python 3.11 is required ^(FreeGSNKE / scipy wheels^).
  echo       Install from https://www.python.org/downloads/release/python-3119/
  echo       Or: winget install Python.Python.3.11
  echo       Then re-run setup_fresh.cmd
  where py >nul 2>nul && py -0p 2>nul
  exit /b 1
)

echo [INFO] Using: %PY_BOOT%

if not exist ".venv\Scripts\python.exe" (
  if exist ".venv" (
    echo [WARN] .venv exists but python.exe missing — recreating
    rmdir /s /q ".venv" 2>nul
  )
  echo [INFO] Creating .venv
  %PY_BOOT% -m venv .venv
  if errorlevel 1 (
    echo [FAIL] venv creation failed
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [FAIL] activate .venv failed
  exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info[:2]==(3,11) else 1)" >nul 2>nul
if errorlevel 1 (
  echo [FAIL] .venv is not Python 3.11. Delete .venv and re-run setup_fresh.cmd
  python -V
  exit /b 1
)

echo [INFO] Upgrading pip + installing package ^(UI + tests via requirements.txt^)
python -m pip install -U pip setuptools wheel
if errorlevel 1 exit /b 1
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [FAIL] pip install -r requirements.txt failed
  exit /b 1
)

echo [INFO] Ensuring s5cmd ^(FAIR-MAST Level-2 sync^)
python scripts\ensure_s5cmd.py
if errorlevel 1 (
  echo [FAIL] s5cmd bootstrap failed — downloads will not work
  exit /b 1
)

echo [INFO] Ensuring FreeGSNKE env ^(required by configs\default.json execute flags^)
python scripts\ensure_freegsnke_env.py
if errorlevel 1 (
  echo [FAIL] FreeGSNKE env bootstrap failed
  echo       Install Python 3.11 and retry, or see scripts\ensure_freegsnke_env.py
  exit /b 1
)

echo.
echo [OK] Fresh setup complete.
echo.
echo Next steps:
echo   1^) mast-freegsnke doctor --config configs\default.json
echo   2^) run_pipeline.cmd          ^(shot-only reconstruct^)
echo   3^) run_ui.cmd                ^(browser console on http://127.0.0.1:8050^)
echo.
echo Optional groups ^(Soft X-rays, Thomson, CXRS, …^) download when available;
echo missing groups are warnings only — see https://mastapp.site/level2-data.html
echo.
exit /b 0
