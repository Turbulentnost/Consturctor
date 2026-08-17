@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Platform packages and services — run from repo root (Consturctor/)
rem Usage: scripts\install_platform.cmd

cd /d "%~dp0.." || exit /b 1
set "ROOT=%CD%"

where py >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python launcher "py" not found. Install Python 3.12+.
    exit /b 1
)

call :install "platform-contracts" "%ROOT%\platform-contracts"
call :install "platform-db" "%ROOT%\platform-db"
call :install "platform-service-common" "%ROOT%\platform-service-common"
call :install "backend" "%ROOT%\backend"

call :install "platform-kpi" "%ROOT%\services\platform-kpi"
call :install "platform-tool-imap" "%ROOT%\services\platform-tool-imap"
call :install "platform-tool-onec" "%ROOT%\services\platform-tool-onec"
call :install "platform-orchestrator" "%ROOT%\services\platform-orchestrator"
call :install "platform-tool-shell" "%ROOT%\services\platform-tool-shell"
call :install "platform-tool-browser" "%ROOT%\services\platform-tool-browser"
call :install "platform-tool-com" "%ROOT%\services\platform-tool-com"
call :install "platform-tool-filesystem" "%ROOT%\services\platform-tool-filesystem"
call :install "platform-desktop-launcher" "%ROOT%\services\platform-desktop-launcher"
call :install "platform-desktop-host" "%ROOT%\services\platform-desktop-host"

echo.
echo Installing test dependencies...
py -3.12 -m pip install pytest httpx
if errorlevel 1 exit /b 1

echo.
echo Done.
exit /b 0

:install
echo.
echo Installing %~1...
py -3.12 -m pip install -e "%~2"
if errorlevel 1 (
    echo ERROR: failed to install %~1
    exit /b 1
)
exit /b 0
