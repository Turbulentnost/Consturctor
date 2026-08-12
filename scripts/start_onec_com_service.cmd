@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo === 1C thin client COM microservice (:7831, 32-bit Python) ===
if not exist "logs" mkdir "logs" >nul 2>&1

if exist "infra\.env" (
  for /f "usebackq tokens=1,* delims==" %%A in (`findstr /B /I "USE_STUBS= ERP_LOGIN= ERP_PASSWORD= ODATA_BASE_URL= ONEC_COM_SERVER= ONEC_COM_REF= ONEC_COM_USER= ONEC_COM_PASSWORD= ONEC_COM_CONNECTION_STRING= ONEC_COM_PROGID=" "infra\.env"`) do (
    set "%%A=%%B"
  )
)
if not defined USE_STUBS set "USE_STUBS=false"

py -0p 2>nul | findstr /I /C:"-32" >nul
if errorlevel 1 (
  echo ERROR: Python 3.12 32-bit not found. Run scripts\ensure_com_python.cmd first.
  exit /b 1
)

echo Check :7831 ...
powershell -NoProfile -Command "if((Test-NetConnection 127.0.0.1 -Port 7831 -WarningAction SilentlyContinue).TcpTestSucceeded){exit 0}else{exit 1}"
if not errorlevel 1 (
  echo OK already listening on :7831
  exit /b 0
)

set "CONSTRUCTOR_ROOT=%CD%"
set "CMD=set API_PORT=7831&& set USE_STUBS=%USE_STUBS%&& set CONSTRUCTOR_ROOT=%CD%"
if defined ERP_LOGIN set "CMD=%CMD%&& set ERP_LOGIN=%ERP_LOGIN%"
if defined ERP_PASSWORD set "CMD=%CMD%&& set ERP_PASSWORD=%ERP_PASSWORD%"
if defined ODATA_BASE_URL set "CMD=%CMD%&& set ODATA_BASE_URL=%ODATA_BASE_URL%"
if defined ONEC_COM_SERVER set "CMD=%CMD%&& set ONEC_COM_SERVER=%ONEC_COM_SERVER%"
if defined ONEC_COM_REF set "CMD=%CMD%&& set ONEC_COM_REF=%ONEC_COM_REF%"
set "CMD=%CMD%&& py -3.12-32 -m platform_tool_onec_com.main"

powershell -NoProfile -Command ^
  "$wd='%CD%'; Start-Process cmd.exe -ArgumentList @('/c','%CMD%') -WorkingDirectory $wd -WindowStyle Hidden -RedirectStandardOutput (Join-Path $wd 'logs\onec-com.out.log') -RedirectStandardError (Join-Path $wd 'logs\onec-com.err.log') | Out-Null"

echo Waiting for :7831 ...
set /a "_w=0"
:wait7831
powershell -NoProfile -Command "exit ([int]-not (Test-NetConnection 127.0.0.1 -Port 7831 -WarningAction SilentlyContinue).TcpTestSucceeded)"
if not errorlevel 1 goto ok
timeout /t 1 /nobreak >nul
set /a "_w+=1"
if %_w% GEQ 30 goto fail
goto wait7831

:fail
echo ERROR: onec-com service failed. See logs\onec-com.err.log
exit /b 1

:ok
echo OK platform-tool-onec-com :7831
exit /b 0
