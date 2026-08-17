@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo === Restart 1C COM microservice (:7831) ===
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":7831" ^| findstr "LISTENING"') do (
  echo Stop PID %%P on :7831
  taskkill /PID %%P /F >nul 2>&1
)
timeout /t 1 /nobreak >nul
call "%~dp0start_onec_com_service.cmd"
