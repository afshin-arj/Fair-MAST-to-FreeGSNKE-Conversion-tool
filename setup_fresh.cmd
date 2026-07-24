@echo off
setlocal EnableExtensions

REM ---------------------------------------------------------------------------
REM Fresh-machine bootstrap for Fair-MAST → FreeGSNKE (Windows)
REM Clone the repo, run this once, then use run_pipeline.cmd / run_ui.cmd
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
  if errorlevel 1 (
    echo [FAIL] Python 3.11+ not found. Install from https://www.python.org/downloads/
    exit /b 1
  )
  set "PY_BOOT=python"
)

echo [INFO] Using: %PY_BOOT%

if not exist ".venv\Scripts\python.exe" (
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

echo [INFO] Upgrading pip + installing package ^(with UI extras^)
python -m pip install -U pip
if errorlevel 1 exit /b 1
if exist requirements.txt (
  python -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
)
python -m pip install -e ".[ui]"
if errorlevel 1 exit /b 1

echo [INFO] Ensuring s5cmd ^(FAIR-MAST Level-2 sync^)
python scripts\ensure_s5cmd.py
if errorlevel 1 (
  echo [WARN] s5cmd helper returned non-zero — install s5cmd manually if downloads fail
)

echo [INFO] Ensuring FreeGSNKE env ^(optional until you execute solvers^)
if exist scripts\ensure_freegsnke_env.py (
  python scripts\ensure_freegsnke_env.py
  if errorlevel 1 (
    echo [WARN] FreeGSNKE env helper returned non-zero — pipeline download/extract still works
  )
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
