@echo off
cd /d "%~dp0"
taskkill /IM ConstructorDesktop.exe /F >nul 2>&1
taskkill /IM DesktopHost.exe /F >nul 2>&1
taskkill /IM DesktopLauncher.exe /F >nul 2>&1
timeout /t 2 /nobreak >nul
start "" "%~dp0ConstructorDesktop.exe"
exit /b 0
