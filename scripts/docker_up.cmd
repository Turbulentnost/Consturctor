@echo off
setlocal EnableExtensions

rem Start full Constructor platform via Docker Compose.
rem Usage: scripts\docker_up.cmd

set "ROOT=%~dp0.."
cd /d "%ROOT%\infra" || exit /b 1

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo Created infra\.env from .env.example
)

echo Building and starting all services...
docker compose up -d --build
if errorlevel 1 exit /b 1

echo.
echo Waiting for health checks...
timeout /t 15 /nobreak >nul

echo.
echo URLs:
echo   Gateway:   http://127.0.0.1:7812/health
echo   Demo UI:   http://127.0.0.1:8790/
echo   RabbitMQ:  http://127.0.0.1:15673/  (guest/guest)
echo.
echo All services:
docker compose ps
echo.
echo Celery:
docker compose ps platform-orchestrator-worker platform-orchestrator-beat platform-tool-imap-worker platform-tool-onec-worker
echo.
echo Health check:
call "%~dp0check_platform_health.cmd"
exit /b %ERRORLEVEL%
