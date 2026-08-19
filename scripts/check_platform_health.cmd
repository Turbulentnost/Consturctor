@echo off
setlocal EnableExtensions

set "ROOT=%~dp0.."
set FAIL=0

echo HTTP health:
for %%P in (7820 7821 7822 7823 7824 7825 7812 7830 7831) do (
    curl -sf http://127.0.0.1:%%P/health >nul 2>&1
    if errorlevel 1 (
        echo   [FAIL] :%%P/health
        set FAIL=1
    ) else (
        echo   [ OK ] :%%P/health
    )
)

curl -sf http://127.0.0.1:8790/ >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] :8790 demo UI
    set FAIL=1
) else (
    echo   [ OK ] :8790 demo UI
)

echo.
echo Docker Compose (infra):
cd /d "%ROOT%\infra" || exit /b 1
docker compose ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}" 2>nul
if errorlevel 1 (
    echo   [FAIL] docker compose ps
    set FAIL=1
)

echo.
echo Celery workers:
for %%S in (platform-orchestrator-worker platform-orchestrator-beat platform-tool-imap-worker platform-tool-onec-worker) do (
    docker compose ps %%S --format "{{.Service}}: {{.Status}}" 2>nul | findstr /I "Up" >nul
    if errorlevel 1 (
        echo   [FAIL] %%S
        set FAIL=1
    ) else (
        for /f "delims=" %%L in ('docker compose ps %%S --format "{{.Service}}: {{.Status}}" 2^>nul') do echo   [ OK ] %%L
    )
)

if %FAIL%==1 (
    echo.
    echo Some services are down.
    echo   Docker: scripts\docker_up.cmd  OR  scripts\start_all_local.cmd
    echo   COM :7831: scripts\restart_onec_com_service.cmd
    echo Logs: cd infra ^&^& docker compose logs -f SERVICE
    exit /b 1
)
exit /b 0
