@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------------
REM MAST -> FreeGSNKE Pipeline launcher (Windows)
REM - Creates/uses .venv
REM - Installs/updates package + optional extras
REM - Runs interactive shot workflow
REM - Captures full log to logs\run_<timestamp>.log (tee to console via PowerShell)
REM
REM Author: © 2026 Afshin Arjhangmehr
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

REM If invoked internally, skip tee wrapper.
if /i "%~1"=="__INTERNAL__" goto :MAIN

REM Generate timestamp safely and tee output to log via PowerShell
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "LOG_DIR=%CD%\logs"
set "LOG_FILE=%LOG_DIR%\run_%TS%.log"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$log='%LOG_FILE%'; New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null; " ^
  "Write-Host ('[INFO] Logging to: ' + $log); " ^
  "cmd /c '\"%~f0\" __INTERNAL__' 2>&1 | Tee-Object -FilePath $log; exit $LASTEXITCODE"

exit /b %ERRORLEVEL%

:MAIN
echo [INFO] Started: %DATE% %TIME%
echo [INFO] PWD: %CD%
echo [INFO] OS: %OS%

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
  echo [FAIL] Failed to activate virtual environment.
  exit /b 1
)

echo [INFO] Python:
python -V
echo [INFO] Pip:
python -m pip -V

echo [INFO] Capturing pip freeze
python -m pip freeze > "%LOG_DIR%\pip_freeze_%TS%.txt"
echo [INFO] Wrote: %LOG_DIR%\pip_freeze_%TS%.txt


echo [INFO] Upgrading pip/setuptools/wheel
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
  echo [FAIL] pip upgrade failed.
  exit /b 1
)

echo [INFO] Installing repo (editable) with extras: [zarr,dev]
python -m pip install -e ".[zarr,dev]"
if errorlevel 1 (
  echo [FAIL] Package install failed.
  exit /b 1
)

echo.
echo ===========================================================================
echo Interactive Run
echo ===========================================================================
echo.

set "CONFIG_PATH="
set /p CONFIG_PATH=Enter config path (default: configs/default.yaml): 
if "%CONFIG_PATH%"=="" set "CONFIG_PATH=configs/default.yaml"

set "SHOT="
set /p SHOT=Enter MAST shot number (required): 
if "%SHOT%"=="" (
  echo [FAIL] Shot number is required.
  exit /b 1
)

set "MACHINE_DIR="
set /p MACHINE_DIR=Enter machine authority dir (default: machine_authority): 
if "%MACHINE_DIR%"=="" set "MACHINE_DIR=machine_authority"

set "WINDOW_OVERRIDE="
set /p WINDOW_OVERRIDE=Optional window override (blank for auto): 

set "RUN_FREEGSNKE="
set /p RUN_FREEGSNKE=Run FreeGSNKE execution now? (y/n, default y): 
if "%RUN_FREEGSNKE%"=="" set "RUN_FREEGSNKE=y"

set "RUN_METRICS="
set /p RUN_METRICS=Compute contract residual metrics? (y/n, default y): 
if "%RUN_METRICS%"=="" set "RUN_METRICS=y"

set "ARGS=run --config ""%CONFIG_PATH%"" --shot %SHOT% --machine-authority ""%MACHINE_DIR%"""

if not "%WINDOW_OVERRIDE%"=="" (
  set "ARGS=%ARGS% --window-override ""%WINDOW_OVERRIDE%"""
)

if /i "%RUN_FREEGSNKE%"=="n" (
  set "ARGS=%ARGS% --skip-freegsnke"
)

if /i "%RUN_METRICS%"=="n" (
  set "ARGS=%ARGS% --skip-metrics"
)

echo.
echo [INFO] Running: mast-freegsnke %ARGS%
echo.

mast-freegsnke %ARGS%
set "RC=%ERRORLEVEL%"

echo.
echo [INFO] Completed with exit code %RC%
exit /b %RC%
