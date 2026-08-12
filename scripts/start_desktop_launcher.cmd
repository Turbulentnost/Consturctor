@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

if not exist "logs" mkdir "logs" >nul 2>&1

call :port_up 7829
if not errorlevel 1 (
  echo Desktop launcher already running on http://127.0.0.1:7829
  exit /b 0
)

echo Starting platform-desktop-launcher on http://127.0.0.1:7829 ...
set "CONSTRUCTOR_ROOT=%CD%"
powershell -NoProfile -Command ^
  "$wd='%CD%';" ^
  "Start-Process cmd.exe -ArgumentList @('/c','set API_PORT=7829&& set CONSTRUCTOR_ROOT=%CD%&& py -3.12 -m platform_desktop_launcher.main') -WorkingDirectory $wd -WindowStyle Hidden -RedirectStandardOutput (Join-Path $wd 'logs\desktop-launcher.out.log') -RedirectStandardError (Join-Path $wd 'logs\desktop-launcher.err.log') | Out-Null"

set /a "ELAPSED=0"
:wait_loop
timeout /t 2 /nobreak >nul
set /a "ELAPSED+=2"
call :port_up 7829
if not errorlevel 1 (
  echo Desktop launcher ready.
  exit /b 0
)
if %ELAPSED% GEQ 20 goto fail
goto wait_loop

:fail
echo ERROR: desktop launcher did not start. See logs\desktop-launcher.err.log
exit /b 1

:port_up
powershell -NoProfile -Command ^
  "$r=Test-NetConnection -ComputerName 127.0.0.1 -Port %1 -WarningAction SilentlyContinue; if ($r.TcpTestSucceeded) { exit 0 } else { exit 1 }"
exit /b %ERRORLEVEL%
