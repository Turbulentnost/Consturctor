@echo off
setlocal
cd /d "%~dp0.."
echo Mock agent scenarios (orchestrator :7825, USE_STUBS=true)
echo.
py -3.12 scripts\run_agent_mocks.py --list
echo.
if "%~1"=="" (
    py -3.12 scripts\run_agent_mocks.py --all
) else (
    py -3.12 scripts\run_agent_mocks.py %*
)
exit /b %ERRORLEVEL%
