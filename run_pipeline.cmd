@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------------
REM MAST -> FreeGSNKE Pipeline launcher (Windows)
REM - Creates/uses .venv
REM - Installs/updates package + optional extras
REM - Runs interactive shot workflow
REM
REM Author: © 2026 Afshin Arjhangmehr
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [FAIL] Python not found on PATH. Install Python 3.9+ and retry.
  exit /b 1
)

if not exist ".venv" (
  echo [INFO] Creating virtual environment: .venv
  python -m venv .venv
  if errorlevel 1 (
    echo [FAIL] venv creation failed.
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [FAIL] Could not activate .venv
  exit /b 1
)

echo [INFO] Upgrading pip...
python -m pip install --upgrade pip >nul
if errorlevel 1 (
  echo [FAIL] pip upgrade failed.
  exit /b 1
)

echo [INFO] Installing package (editable) with extras: zarr,dev
python -m pip install -e ".[zarr,dev]"
if errorlevel 1 (
  echo [FAIL] Package install failed.
  exit /b 1
)

set "DEFAULT_CONFIG=configs\config.example.json"
set "DEFAULT_MACHINE=machine_configs\MAST"
set "DEFAULT_CONTRACTS=configs\diagnostic_contracts.example.json"
set "DEFAULT_COILMAP=configs\coil_map.example.json"

echo.
set /p CFG=Config path [!DEFAULT_CONFIG!]:
if "!CFG!"=="" set "CFG=!DEFAULT_CONFIG!"

echo.
echo [STEP] Environment doctor
python -m mast_freegsnke.cli doctor --config "!CFG!"
echo.

set /p SHOT=Shot number (e.g. 30201):
if "!SHOT!"=="" (
  echo [FAIL] Shot number is required.
  exit /b 1
)

set /p MACH=Machine directory [!DEFAULT_MACHINE!]:
if "!MACH!"=="" set "MACH=!DEFAULT_MACHINE!"

set /p TSTART=Window override tstart [s] (blank = auto):
set /p TEND=Window override tend [s] (blank = auto):

set /p EXE=Execute FreeGSNKE now? (y/N):
if /I "!EXE!"=="y" (
  set "EXEC_FLAG=--execute-freegsnke"
  set /p MODE=FreeGSNKE mode [both|inverse|forward] (default both):
  if "!MODE!"=="" set "MODE=both"
  set "MODE_FLAG=--freegsnke-mode !MODE!"
  set /p FGPY=Optional: path to FreeGSNKE python exe (blank = use config):
  if not "!FGPY!"=="" (
    set "FGPY_FLAG=--freegsnke-python \"!FGPY!\""
  ) else (
    set "FGPY_FLAG="
  )
) else (
  set "EXEC_FLAG="
  set "MODE_FLAG="
  set "FGPY_FLAG="
)

set /p MET=Enable contract metrics? (y/N):
if /I "!MET!"=="y" (
  set "MET_FLAG=--enable-contract-metrics"
  set /p CONTRACTS=Contracts JSON [!DEFAULT_CONTRACTS!]:
  if "!CONTRACTS!"=="" set "CONTRACTS=!DEFAULT_CONTRACTS!"
  set /p COILMAP=Coil-map JSON [!DEFAULT_COILMAP!]:
  if "!COILMAP!"=="" set "COILMAP=!DEFAULT_COILMAP!"
  set "CONTRACTS_FLAG=--contracts \"!CONTRACTS!\""
  set "COILMAP_FLAG=--coil-map \"!COILMAP!\""
) else (
  set "MET_FLAG="
  set "CONTRACTS_FLAG="
  set "COILMAP_FLAG="
)

set "TSTART_FLAG="
set "TEND_FLAG="
if not "!TSTART!"=="" set "TSTART_FLAG=--tstart !TSTART!"
if not "!TEND!"=="" set "TEND_FLAG=--tend !TEND!"

echo.
echo [RUN] mast-freegsnke run --shot !SHOT! --config "!CFG!" --machine "!MACH!" !TSTART_FLAG! !TEND_FLAG! !EXEC_FLAG! !MODE_FLAG! !FGPY_FLAG! !MET_FLAG! !CONTRACTS_FLAG! !COILMAP_FLAG!
echo.

python -m mast_freegsnke.cli run --shot !SHOT! --config "!CFG!" --machine "!MACH!" !TSTART_FLAG! !TEND_FLAG! !EXEC_FLAG! !MODE_FLAG! !FGPY_FLAG! !MET_FLAG! !CONTRACTS_FLAG! !COILMAP_FLAG!
set ERR=%ERRORLEVEL%

echo.
if %ERR% NEQ 0 (
  echo [FAIL] Pipeline exited with code %ERR%.
  exit /b %ERR%
) else (
  echo [OK] Completed. See runs\shot_!SHOT!\
)

exit /b 0
