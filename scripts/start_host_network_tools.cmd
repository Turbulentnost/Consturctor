@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

echo === Unified desktop host (:7830) - tools outside Docker ===
if not exist "logs" mkdir "logs" >nul 2>&1

if exist "infra\.env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /B /I "USE_STUBS= IMAP_HOST= IMAP_PORT= IMAP_USERNAME= IMAP_PASSWORD= IMAP_MAILBOX= IMAP_CONNECT_TIMEOUT_SEC= ERP_LOGIN= ERP_PASSWORD= ODATA_BASE_URL= ONEC_COM_SERVER= ONEC_COM_REF= ONEC_COM_USER= ONEC_COM_PASSWORD= ONEC_COM_CONNECTION_STRING= ONEC_COM_PYTHON=" "infra\.env"`) do (
    set "%%A=%%B"
  )
)
if not defined USE_STUBS set "USE_STUBS=false"
if not defined IMAP_MAILBOX set "IMAP_MAILBOX=INBOX"
if not defined IMAP_CONNECT_TIMEOUT_SEC set "IMAP_CONNECT_TIMEOUT_SEC=120"

set "DATABASE_URL=postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor"
set "URL_WHITELIST=localhost,127.0.0.1,turbo-don.ru,161.ru,ria.ru,don24.ru,donnews.ru,yandex.ru,ya.ru,google.com,duckduckgo.com,wikipedia.org,ru.wikipedia.org,en.wikipedia.org,calend.ru,www.calend.ru,vseinstrumenti.ru,rbc.ru,kommersant.ru,lenta.ru,gazeta.ru,mail.ru,vodokanalrnd.ru,rostov-zkh.ru"
set "CONSTRUCTOR_ROOT=%CD%"

echo [1] Stop Docker IMAP/browser workers ...
pushd infra
docker compose stop platform-tool-imap platform-tool-imap-worker platform-tool-browser >nul 2>&1
popd

set "FS_ROOT_ALLOWLIST="
for /f "usebackq delims=" %%A in (`py -3.12 -c "from pathlib import Path; from platform_tool_filesystem.desktop_paths import default_fs_allowlist; print(default_fs_allowlist(repo_data_filesystem=Path(r'%CD%') / 'data' / 'filesystem'))"`) do set "FS_ROOT_ALLOWLIST=%%A"
if not defined FS_ROOT_ALLOWLIST set "FS_ROOT_ALLOWLIST=%CD%\data\filesystem"
set "SHELL_CWD_ROOTS=%CD%\data\shell-native"
if not exist "data\filesystem" mkdir "data\filesystem" >nul 2>&1
if not exist "data\shell-native" mkdir "data\shell-native" >nul 2>&1

echo [2] Restart unified desktop host :7830 ...
powershell -NoProfile -Command ^
  "foreach($p in 7830,7821,7824){Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"
timeout /t 2 /nobreak >nul

powershell -NoProfile -Command ^
  "$wd='%CD%';" ^
  "$cmd='set API_PORT=7830&& set USE_STUBS=%USE_STUBS%&& set CONSTRUCTOR_ROOT=%CD%&& set DATABASE_URL=%DATABASE_URL%&& set URL_WHITELIST=%URL_WHITELIST%&& set FS_ROOT_ALLOWLIST=%FS_ROOT_ALLOWLIST%&& set SHELL_CWD_ROOTS=%SHELL_CWD_ROOTS%';" ^
  "if('%IMAP_HOST%'){$cmd+='&& set IMAP_HOST=%IMAP_HOST%'};" ^
  "if('%IMAP_PORT%'){$cmd+='&& set IMAP_PORT=%IMAP_PORT%'};" ^
  "if('%IMAP_USERNAME%'){$cmd+='&& set IMAP_USERNAME=%IMAP_USERNAME%'};" ^
  "if('%IMAP_PASSWORD%'){$cmd+='&& set IMAP_PASSWORD=%IMAP_PASSWORD%'};" ^
  "if('%ERP_LOGIN%'){$cmd+='&& set ERP_LOGIN=%ERP_LOGIN%'};" ^
  "if('%ERP_PASSWORD%'){$cmd+='&& set ERP_PASSWORD=%ERP_PASSWORD%'};" ^
  "if('%ODATA_BASE_URL%'){$cmd+='&& set ODATA_BASE_URL=%ODATA_BASE_URL%'};" ^
  "if('%ONEC_COM_SERVER%'){$cmd+='&& set ONEC_COM_SERVER=%ONEC_COM_SERVER%'};" ^
  "if('%ONEC_COM_REF%'){$cmd+='&& set ONEC_COM_REF=%ONEC_COM_REF%'};" ^
  "if('%ONEC_COM_PYTHON%'){$cmd+='&& set ONEC_COM_PYTHON=%ONEC_COM_PYTHON%'};" ^
  "$cmd+='&& set IMAP_MAILBOX=%IMAP_MAILBOX%&& set IMAP_CONNECT_TIMEOUT_SEC=%IMAP_CONNECT_TIMEOUT_SEC%&& py -3.12 -m platform_desktop_host.main';" ^
  "Start-Process cmd.exe -ArgumentList @('/c',$cmd) -WorkingDirectory $wd -WindowStyle Hidden -RedirectStandardOutput (Join-Path $wd 'logs\desktop-host.out.log') -RedirectStandardError (Join-Path $wd 'logs\desktop-host.err.log') | Out-Null"

echo [3] Start launcher :7829 ...
powershell -NoProfile -Command ^
  "if(-not (Test-NetConnection 127.0.0.1 -Port 7829 -WarningAction SilentlyContinue).TcpTestSucceeded){" ^
  "  $wd='%CD%'; Start-Process cmd.exe -ArgumentList @('/c','set API_PORT=7829&& set USE_STUBS=%USE_STUBS%&& set CONSTRUCTOR_ROOT=%CD%&& py -3.12 -m platform_desktop_launcher.main') -WorkingDirectory $wd -WindowStyle Hidden -RedirectStandardOutput (Join-Path $wd 'logs\desktop-launcher.out.log') -RedirectStandardError (Join-Path $wd 'logs\desktop-launcher.err.log') | Out-Null }"

echo [4] Wait for :7830 ...
set /a "_w=0"
:wait7830
powershell -NoProfile -Command "exit ([int]-not (Test-NetConnection 127.0.0.1 -Port 7830 -WarningAction SilentlyContinue).TcpTestSucceeded)"
if not errorlevel 1 goto host_ready
timeout /t 1 /nobreak >nul
set /a "_w+=1"
if %_w% GEQ 45 goto host_fail
goto wait7830

:host_fail
echo ERROR: desktop host :7830 failed. See logs\desktop-host.err.log
exit /b 1

:host_ready
echo OK desktop host :7830

echo [3b] Start 1C COM microservice :7831 ...
call "%~dp0start_onec_com_service.cmd"
if errorlevel 1 (
  echo WARN: onec-com :7831 not started — install 32-bit Python: scripts\ensure_com_python.cmd
)

echo [5] Recreate gateway/orchestrator (route tools to host.docker.internal:7830) ...
pushd infra
docker compose up -d --no-deps --force-recreate platform-orchestrator-api constructor-gateway >nul
docker compose stop platform-tool-imap platform-tool-imap-worker platform-tool-browser >nul 2>&1
popd

echo.
echo Unified host ready. Smoke: scripts\smoke_host_tools.cmd
exit /b 0
