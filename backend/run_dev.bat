@echo off
cd /d "%~dp0"
set "PORT=7812"
rem Local dev: JWT is not tied to Redis session (avoids 401 after LAN/localhost switch).
if not defined AUTH_SKIP_SESSION_LOCK set "AUTH_SKIP_SESSION_LOCK=1"
rem Dev bypass: read AUTH_SKIP_ERP_SQL from backend\.env before gateway default (do not override explicit env).
if not defined AUTH_SKIP_ERP_SQL (
  for /f %%I in ('powershell -NoProfile -WindowStyle Hidden -Command ^
    "$p=Join-Path (Get-Location) '.env'; if(-not (Test-Path $p)){ '0'; exit 0 }; foreach($raw in Get-Content $p -Encoding UTF8){ $t=$raw.Trim(); if($t -match '^AUTH_SKIP_ERP_SQL\s*=\s*(.+)$' -and -not $t.StartsWith('#')){ $v=$Matches[1].Trim(); if($v -match '^(1|true|yes|on)$'){ '1'; exit 0 } if($v -match '^(0|false|no|off)$'){ '0'; exit 0 } } }; foreach($raw in Get-Content $p -Encoding UTF8){ $t=$raw.Trim(); if($t -match '^ERP_LOGIN\s*=\s*(.+)$' -and -not $t.StartsWith('#')){ if($Matches[1].Trim()){ '1'; exit 0 } } }; '0'"') do set "AUTH_SKIP_ERP_SQL=%%I"
)
if "%AUTH_SKIP_ERP_SQL%"=="1" echo AUTH_SKIP_ERP_SQL=1 ^(local login bypass, no erp_pm SQL^)
rem AUTH_ERP_GATEWAY_URL from .env (line present but empty = direct erp_pm SQL, no 157:7812 proxy).
if not defined AUTH_ERP_GATEWAY_URL (
  set "GATEWAY_IN_DOTENV=0"
  if exist ".env" for /f "usebackq tokens=1,* delims==" %%A in (`findstr /B /I /C:"AUTH_ERP_GATEWAY_URL=" .env 2^>nul`) do (
    set "AUTH_ERP_GATEWAY_URL=%%B"
    set "GATEWAY_IN_DOTENV=1"
  )
  if "%GATEWAY_IN_DOTENV%"=="0" if not "%AUTH_SKIP_ERP_SQL%"=="1" set "AUTH_ERP_GATEWAY_URL=http://192.168.1.157:7812"
)
if "%AUTH_SKIP_ERP_SQL%"=="0" if "%AUTH_ERP_GATEWAY_URL%"=="" echo AUTH_ERP_GATEWAY_URL= ^(direct erp_pm SQL^)
if not "%AUTH_ERP_GATEWAY_URL%"=="" echo AUTH_ERP_GATEWAY_URL=%AUTH_ERP_GATEWAY_URL%

rem Do not probe/kill :7812 — a running backend may be busy with erp_pm ODBC.
rem If port is taken, uvicorn will fail; stop the other process manually.

if not exist ".env" (
  echo Copy .env.example to .env and configure DATABASE_URL / ERP access.
  copy /Y .env.example .env >nul
)

if not defined API_HOST set "API_HOST=127.0.0.1"
echo Starting orchestrator backend on %API_HOST%:%PORT% ...
py -3.12 -m app.main
if errorlevel 1 if not "%ORCH_IN_CURSOR%"=="1" pause
