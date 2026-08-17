@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo === Desktop tools preflight ===
echo.

rem Propagate host env from infra/.env when present.
if exist "infra\.env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /B /I "USE_STUBS= IMAP_HOST= IMAP_PORT= IMAP_USERNAME= IMAP_PASSWORD= IMAP_MAILBOX= IMAP_CONNECT_TIMEOUT_SEC= ERP_LOGIN= ERP_PASSWORD= ODATA_BASE_URL= ONEC_COM_SERVER= ONEC_COM_REF= URL_WHITELIST=" "infra\.env"`) do (
    set "%%A=%%B"
  )
)
if not defined USE_STUBS set "USE_STUBS=false"
if not defined IMAP_MAILBOX set "IMAP_MAILBOX=INBOX"
if not defined IMAP_CONNECT_TIMEOUT_SEC set "IMAP_CONNECT_TIMEOUT_SEC=120"
set "CONSTRUCTOR_ROOT=%CD%"
echo USE_STUBS=%USE_STUBS%
echo.

echo [1/3] Checking desktop launcher :7829 ...
call :port_up 7829
if errorlevel 1 (
  echo Starting desktop launcher :7829 ...
  if not exist "logs" mkdir "logs" >nul 2>&1
  set "CONSTRUCTOR_ROOT=%CD%"
  powershell -NoProfile -Command ^
    "$wd='%CD%'; $stubs='%USE_STUBS%';" ^
    "Start-Process cmd.exe -ArgumentList @('/c',('set API_PORT=7829&& set USE_STUBS='+$stubs+'&& set CONSTRUCTOR_ROOT=%CD%&& py -3.12 -m platform_desktop_launcher.main')) -WorkingDirectory $wd -WindowStyle Hidden -RedirectStandardOutput (Join-Path $wd 'logs\desktop-launcher.out.log') -RedirectStandardError (Join-Path $wd 'logs\desktop-launcher.err.log') | Out-Null"
  timeout /t 3 /nobreak >nul
)

call :port_up 7829
if errorlevel 1 (
  echo ERROR: launcher :7829 failed. See logs\desktop-launcher.err.log
) else (
  echo OK launcher :7829
)

echo.
echo [2/3] Ensuring unified desktop host :7830 via launcher ...
call :port_up 7830
if not errorlevel 1 (
  echo Restarting desktop-host :7830 to apply infra/.env ...
  powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 7830 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
  timeout /t 2 /nobreak >nul
)
call :port_up 7830
if errorlevel 1 (
  py -3.12 -c "import json,urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:7829/api/v1/ensure', data=json.dumps({'port':7830,'tool_name':'com.list_apps','wait_seconds':60}).encode(), headers={'Content-Type':'application/json'}, method='POST'), timeout=90).read()"
  if errorlevel 1 (
    echo WARNING: launcher ensure for :7830 failed. Will still start legacy ports.
  ) else (
    echo OK desktop-host :7830
  )
) else (
  echo OK desktop-host :7830 already up
)

echo.
echo [3/3] Ensuring legacy COM/FS/shell-native :7826/:7827/:7828 ...
call "scripts\start_desktop_tools.cmd"
if errorlevel 1 (
  echo WARNING: start_desktop_tools.cmd returned errorlevel %ERRORLEVEL%
)

echo.
echo Port status:
call :report_port 7826 COM-legacy
call :report_port 7827 FS-legacy
call :report_port 7828 shell-native-legacy
call :report_port 7829 launcher
call :report_port 7830 desktop-host

echo.
echo If COM/Outlook tools fail from Docker, keep these host ports UP and retry.
echo Hint: scripts\ensure_desktop_tools.cmd
exit /b 0

:report_port
call :port_up %1
if errorlevel 1 (
  echo   DOWN  :%1  %~2
) else (
  echo   UP    :%1  %~2
)
exit /b 0

:port_up
powershell -NoProfile -Command ^
  "$r=Test-NetConnection -ComputerName 127.0.0.1 -Port %1 -WarningAction SilentlyContinue; if ($r.TcpTestSucceeded) { exit 0 } else { exit 1 }"
exit /b %ERRORLEVEL%
