@echo off
setlocal EnableExtensions

REM ---------------------------------------------------------------------------
REM Shot-only Dash UI launcher (Windows)
REM Enter a MAST shot number in the browser; pipeline uses configs\default.json
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] .venv missing — running setup_fresh.cmd
  call "%~dp0setup_fresh.cmd"
  if errorlevel 1 exit /b 1
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [FAIL] Failed to activate .venv
  exit /b 1
)

echo [INFO] Ensuring UI package is installed ^(dash / plotly^)
python -m pip install -r requirements.txt -q
if errorlevel 1 (
  echo [FAIL] pip install -r requirements.txt failed
  exit /b 1
)

set "PORT=8050"
if not "%~1"=="" set "PORT=%~1"

echo [INFO] Starting UI on http://127.0.0.1:%PORT%
python -m mast_freegsnke.cli ui --config configs\default.json --port %PORT%
exit /b %ERRORLEVEL%
