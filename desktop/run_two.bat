@echo off
cd /d "%~dp0"
start "turbobot" cmd /c "%~dp0run_dev.bat"
timeout /t 2 /nobreak >nul
start "turbobot-anna" cmd /c "%~dp0run_anna.bat"
