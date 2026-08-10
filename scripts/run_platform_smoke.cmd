@echo off
setlocal EnableExtensions

rem Smoke: validate docker-compose and run unit tests
set "ROOT=%~dp0.."
cd /d "%ROOT%\infra"
docker compose config >nul
if errorlevel 1 (
    echo docker compose config FAILED
    exit /b 1
)
echo docker-compose.yml OK

cd /d "%ROOT%"
py -3.12 -m pytest tests\test_platform_contracts.py tests\test_platform_tools_stub.py tests\test_agent_mocks.py -q
exit /b %ERRORLEVEL%
