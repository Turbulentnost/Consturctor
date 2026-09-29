@echo off
cd /d "%~dp0"
title Orchestrator local (backend + desktop)

powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0scripts\patch_orchestrator_roaming_local.ps1"
if errorlevel 1 (
  echo Failed to patch %%APPDATA%%\Orchestrator\.env
  pause
  exit /b 1
)

echo.
echo Cursor / single terminal: scripts\run_dev_cursor.ps1
echo (no extra cmd windows; backend in background, Vite in foreground)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run_dev_cursor.ps1"
exit /b %ERRORLEVEL%
