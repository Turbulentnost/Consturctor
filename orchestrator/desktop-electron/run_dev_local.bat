@echo off
cd /d "%~dp0"
set "BACKEND_URL=http://127.0.0.1:7812"
set "VITE_BACKEND_URL=%BACKEND_URL%"
if not defined ORCH_VITE_PORT set "ORCH_VITE_PORT=5176"
if not defined ORCH_PREFER_LOCAL set "ORCH_PREFER_LOCAL=1"
rem Sidecar: orchestrator/desktop (reset_run_scratch), not Consturctor/desktop.
set "CONSTRUCTOR_DESKTOP_ROOT=%~dp0..\..\desktop"
set "ORCH_BACKEND_ROOT=%~dp0..\..\backend"
title Orchestrator (local)
echo Local dev: backend :7812, sidecar, 1C SOAP (DOK_HTTP_* in backend\.env)
echo Backend: %BACKEND_URL%
echo Desktop: %CONSTRUCTOR_DESKTOP_ROOT%
echo Vite:    %ORCH_VITE_PORT%

powershell -NoProfile -Command ^
  "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7812/health -TimeoutSec 3; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"
if errorlevel 1 (
  echo Local backend :7812 is down — starting orchestrator\backend...
  start "Orchestrator backend" /D "%ORCH_BACKEND_ROOT%" cmd /c run_dev.bat
  echo Waiting for backend health...
  powershell -NoProfile -Command ^
    "$deadline = (Get-Date).AddSeconds(45); while ((Get-Date) -lt $deadline) { try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:7812/health -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 1 }; exit 1"
  if errorlevel 1 (
    echo Backend did not become ready on :7812. Start orchestrator\backend\run_dev.bat manually.
    pause
    exit /b 1
  )
)

npm run dev
if errorlevel 1 pause
