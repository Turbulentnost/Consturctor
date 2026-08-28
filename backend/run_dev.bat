@echo off
cd /d "%~dp0"
set "PORT=7812"

powershell -NoProfile -Command ^
  "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;" ^
  "if(-not $c){exit 0};" ^
  "try{ $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT%/health -TimeoutSec 3; if($r.StatusCode -eq 200){ exit 2 } } catch {};" ^
  "Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 1; exit 0"

if errorlevel 2 (
  echo Backend already running on :%PORT%
  echo http://127.0.0.1:%PORT%/health
  echo http://192.168.2.91:%PORT%/health
  goto :eof
)

echo Starting constructor backend on 0.0.0.0:%PORT% ...
py -3.12 -m app.main
if errorlevel 1 pause
