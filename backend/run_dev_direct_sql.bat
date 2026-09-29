@echo off
cd /d "%~dp0"
rem Local backend: only ODBC ERP_SQL_* on ii1/erp_pm — no AUTH_ERP_GATEWAY_URL fallback.
set "AUTH_ERP_GATEWAY_URL="
set "PORT=7812"
if not defined AUTH_SKIP_SESSION_LOCK set "AUTH_SKIP_SESSION_LOCK=1"
echo Direct erp_pm ODBC (ii1) — AUTH_ERP_GATEWAY_URL disabled for this process.
call run_dev.bat
