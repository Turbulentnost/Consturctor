@echo off
cd /d "%~dp0"
powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0..\..\scripts\patch_orchestrator_roaming_local.ps1" >nul 2>&1
set "BACKEND_URL=http://127.0.0.1:7812"
set "VITE_BACKEND_URL=%BACKEND_URL%"
if not defined ORCH_VITE_PORT set "ORCH_VITE_PORT=5176"
set "ORCH_PREFER_LOCAL=1"
set "ORCH_NO_BACKEND_SPAWN=1"
set "ORCH_BACKEND_ROOT=%~dp0..\..\backend"
set "CONSTRUCTOR_DESKTOP_ROOT=%~dp0..\..\desktop"
title Orchestrator (local)
echo Desktop dev — backend separately: orchestrator\backend\run_dev.bat
echo Backend: %BACKEND_URL%   Vite: %ORCH_VITE_PORT%

if not defined ORCH_DEV_QUIET set "ORCH_DEV_QUIET=1"
if not defined ORCH_CONSOLE_NOTIFY set "ORCH_CONSOLE_NOTIFY=1"
if not defined ORCH_IN_CURSOR set "ORCH_IN_CURSOR=1"
npm run dev
if errorlevel 1 if not "%ORCH_IN_CURSOR%"=="1" pause
