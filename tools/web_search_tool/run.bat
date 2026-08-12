@echo off
setlocal
cd /d "%~dp0"

set "PY=py -3.13"
where py >nul 2>nul || set "PY=python"

if not exist ".venv\Scripts\python.exe" (
  echo [setup] creating venv...
  %PY% -m venv .venv || goto :err
  ".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
)

".venv\Scripts\python.exe" -m websearch %*
set "RC=%ERRORLEVEL%"

if not defined RTS_NONINTERACTIVE pause
exit /b %RC%

:err
echo [error] setup failed
if not defined RTS_NONINTERACTIVE pause
exit /b 1
