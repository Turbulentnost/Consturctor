@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "FAIL=0"
call :port_up 7829
if errorlevel 1 (
  echo DOWN launcher :7829
  set "FAIL=1"
) else (
  echo OK   launcher :7829
)

call :port_up 7830
if errorlevel 1 (
  echo DOWN desktop host :7830 ^(starts on agent invoke or via desktop app^)
) else (
  echo UP   desktop host :7830
)

if "%FAIL%"=="1" (
  echo.
  echo Run: scripts\start_desktop_launcher.cmd  or launch turbobot desktop app
  exit /b 1
)
exit /b 0

:port_up
powershell -NoProfile -Command ^
  "$r=Test-NetConnection -ComputerName 127.0.0.1 -Port %1 -WarningAction SilentlyContinue; if ($r.TcpTestSucceeded) { exit 0 } else { exit 1 }"
exit /b %ERRORLEVEL%
