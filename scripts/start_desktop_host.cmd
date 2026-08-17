@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

if not exist "logs" mkdir "logs" >nul 2>&1

call :port_up 7830
if not errorlevel 1 (
  echo Desktop host already running on http://127.0.0.1:7830
  exit /b 0
)

echo Starting unified desktop host on http://127.0.0.1:7830 ...
set "CONSTRUCTOR_ROOT=%CD%"
set "DATABASE_URL=postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor"
set "URL_WHITELIST=localhost,127.0.0.1,turbo-don.ru,161.ru,ria.ru,don24.ru,donnews.ru,yandex.ru,ya.ru,google.com,duckduckgo.com,wikipedia.org,ru.wikipedia.org,en.wikipedia.org,calend.ru,www.calend.ru,vseinstrumenti.ru,rbc.ru,kommersant.ru,lenta.ru,gazeta.ru,mail.ru"
if exist "infra\.env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /B /I "USE_STUBS= IMAP_HOST= IMAP_PORT= IMAP_USERNAME= IMAP_PASSWORD= IMAP_MAILBOX= IMAP_CONNECT_TIMEOUT_SEC=" "infra\.env"`) do (
    set "%%A=%%B"
  )
)
if not defined USE_STUBS set "USE_STUBS=false"
powershell -NoProfile -Command ^
  "$wd='%CD%';" ^
  "$cmd='set API_PORT=7830&& set USE_STUBS=%USE_STUBS%&& set CONSTRUCTOR_ROOT=%CD%&& set DATABASE_URL=%DATABASE_URL%&& set URL_WHITELIST=%URL_WHITELIST%';" ^
  "if('%IMAP_HOST%'){$cmd+='&& set IMAP_HOST=%IMAP_HOST%'};" ^
  "if('%IMAP_PORT%'){$cmd+='&& set IMAP_PORT=%IMAP_PORT%'};" ^
  "if('%IMAP_USERNAME%'){$cmd+='&& set IMAP_USERNAME=%IMAP_USERNAME%'};" ^
  "if('%IMAP_PASSWORD%'){$cmd+='&& set IMAP_PASSWORD=%IMAP_PASSWORD%'};" ^
  "if('%IMAP_MAILBOX%'){$cmd+='&& set IMAP_MAILBOX=%IMAP_MAILBOX%'};" ^
  "$cmd+='&& py -3.12 -m platform_desktop_host.main';" ^
  "Start-Process cmd.exe -ArgumentList @('/c',$cmd) -WorkingDirectory $wd -WindowStyle Hidden -RedirectStandardOutput (Join-Path $wd 'logs\desktop-host.out.log') -RedirectStandardError (Join-Path $wd 'logs\desktop-host.err.log') | Out-Null"

set /a "ELAPSED=0"
:wait_loop
timeout /t 2 /nobreak >nul
set /a "ELAPSED+=2"
call :port_up 7830
if not errorlevel 1 (
  echo Desktop host ready ^(com + fs + shell + desktop tools^).
  exit /b 0
)
if %ELAPSED% GEQ 30 goto fail
goto wait_loop

:fail
echo ERROR: desktop host did not start. See logs\desktop-host.err.log
exit /b 1

:port_up
powershell -NoProfile -Command ^
  "$r=Test-NetConnection -ComputerName 127.0.0.1 -Port %1 -WarningAction SilentlyContinue; if ($r.TcpTestSucceeded) { exit 0 } else { exit 1 }"
exit /b %ERRORLEVEL%
