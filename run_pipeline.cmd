@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------------
REM MAST -> FreeGSNKE Pipeline launcher (Windows)
REM - Creates/uses .venv
REM - Installs/updates package + optional extras
REM - Runs interactive shot workflow (reprompts on required inputs)
REM - Captures full log to logs\run_<timestamp>.log (PowerShell Transcript; preserves stdin)
REM
REM Author: © 2026 Afshin Arjhangmehr
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

REM If invoked internally, skip transcript wrapper.
if /i "%~1"=="__INTERNAL__" goto :MAIN

REM Timestamp + paths
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "LOG_DIR=%CD%\logs"
set "LOG_FILE=%LOG_DIR%\run_%TS%.log"

REM Use PowerShell transcript (no piping) to preserve interactive stdin.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$log='%LOG_FILE%'; New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null;" ^
  "Write-Host ('[INFO] Logging to: ' + $log);" ^
  "Start-Transcript -Path $log -Append | Out-Null;" ^
  "cmd /c '\"%~f0\" __INTERNAL__ \"%TS%\" \"%LOG_DIR%\" \"%LOG_FILE%\"';" ^
  "$rc=$LASTEXITCODE;" ^
  "Stop-Transcript | Out-Null;" ^
  "exit $rc"

exit /b %ERRORLEVEL%

:MAIN
REM Args passed from wrapper:
REM   %2 = TS, %3 = LOG_DIR, %4 = LOG_FILE
set "TS=%~2"
set "LOG_DIR=%~3"
set "LOG_FILE=%~4"
if "%TS%"=="" (
  for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
)
if "%LOG_DIR%"=="" set "LOG_DIR=%CD%\logs"
if "%LOG_FILE%"=="" set "LOG_FILE=%LOG_DIR%\run_%TS%.log"

echo [INFO] Started: %DATE% %TIME%
echo [INFO] PWD: %CD%
echo [INFO] OS: %OS%
echo [INFO] Log file: %LOG_FILE%

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

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

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
set /p CONFIG_PATH=Enter config path ^(default: configs/default.yaml^): 
if "%CONFIG_PATH%"=="" set "CONFIG_PATH=configs/default.yaml"

:ASK_SHOT
set "SHOT="
set /p SHOT=Enter MAST shot number (required, digits; 'q' to quit): 
if /i "%SHOT%"=="q" (
  echo [INFO] User quit.
  exit /b 0
)
if "%SHOT%"=="" (
  echo [WARN] Shot number is required.
  goto :ASK_SHOT
)
echo %SHOT%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo [WARN] Shot must be digits only (e.g., 30201).
  goto :ASK_SHOT
)

set "MACHINE_DIR="
set /p MACHINE_DIR=Enter machine authority dir ^(default: machine_authority^): 
if "%MACHINE_DIR%"=="" set "MACHINE_DIR=machine_authority"

set "WINDOW_OVERRIDE="
set /p WINDOW_OVERRIDE=Optional window override ^(blank for auto^): 

:ASK_FREEGSNKE
set "RUN_FREEGSNKE="
set /p RUN_FREEGSNKE=Run FreeGSNKE execution now? ^(y/n, default y^): 
if "%RUN_FREEGSNKE%"=="" set "RUN_FREEGSNKE=y"
if /i "%RUN_FREEGSNKE%"=="y" goto :OK_FREEGSNKE
if /i "%RUN_FREEGSNKE%"=="n" goto :OK_FREEGSNKE
echo [WARN] Please enter y or n.
goto :ASK_FREEGSNKE
:OK_FREEGSNKE

:ASK_METRICS
set "RUN_METRICS="
set /p RUN_METRICS=Compute contract residual metrics? ^(y/n, default y^): 
if "%RUN_METRICS%"=="" set "RUN_METRICS=y"
if /i "%RUN_METRICS%"=="y" goto :OK_METRICS
if /i "%RUN_METRICS%"=="n" goto :OK_METRICS
echo [WARN] Please enter y or n.
goto :ASK_METRICS
:OK_METRICS

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
echo [INFO] Log: %LOG_FILE%

REM Keep window open on error if launched by double-click (cmd /c).
set "NEED_PAUSE=0"
echo %CMDCMDLINE% | findstr /i "/c" >nul && set "NEED_PAUSE=1"
if not "%RUN_PIPELINE_NO_PAUSE%"=="" set "NEED_PAUSE=0"
if not "%RC%"=="0" (
  if "%NEED_PAUSE%"=="1" (
    echo.
    echo [INFO] Press any key to close...
    pause >nul
  )
)

exit /b %RC%
