@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
powershell -NoProfile -Command "$p = Get-NetTCPConnection -LocalPort 7831 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if ($p) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }"
timeout /t 2 /nobreak >nul
call "%~dp0start_onec_com_service.cmd"
