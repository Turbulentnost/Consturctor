@echo off
cd /d "%~dp0"
set "PORT=7812"
rem Local dev: JWT is not tied to Redis session (avoids 401 after LAN/localhost switch).
if not defined AUTH_SKIP_SESSION_LOCK set "AUTH_SKIP_SESSION_LOCK=1"
rem 1C auth on gateway when this PC has no ODBC/VPN to erp_pm (desktop may stay on 127.0.0.1:7812).
if not defined AUTH_ERP_GATEWAY_URL set "AUTH_ERP_GATEWAY_URL=http://192.168.1.157:7812"

powershell -NoProfile -Command ^
  "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;" ^
  "if(-not $c){exit 0};" ^
  "try{ $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT%/health -TimeoutSec 5; if($r.StatusCode -eq 200){ exit 2 } } catch {};" ^
  "Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1; exit 0"

if errorlevel 2 (
  echo Backend already running on :%PORT%
  echo http://127.0.0.1:%PORT%/health
  goto :eof
)

if not exist ".env" (
  echo Copy .env.example to .env and configure DATABASE_URL / ERP access.
  copy /Y .env.example .env >nul
)

echo Starting orchestrator backend on 0.0.0.0:%PORT% ...
py -3.12 -m app.main
if errorlevel 1 pause
