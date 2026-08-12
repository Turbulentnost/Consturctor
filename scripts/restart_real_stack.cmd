@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo === Restart stack in REAL mode (USE_STUBS=false) ===
set "USE_STUBS=false"
set "CONSTRUCTOR_ROOT=%CD%"

echo [1] Recreate docker services with infra/.env ...
pushd infra
docker compose up -d --force-recreate constructor-gateway platform-tool-imap platform-tool-onec platform-tool-browser platform-orchestrator-api
popd

echo [2] Restart desktop host (kill :7830 if up) ...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":7830" ^| findstr LISTENING') do (
  taskkill /F /PID %%P >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo [3] ensure_desktop_tools ...
call "scripts\ensure_desktop_tools.cmd"

echo Done. Verify mode=real on imap.fetch / com.outlook.launch.
exit /b 0
