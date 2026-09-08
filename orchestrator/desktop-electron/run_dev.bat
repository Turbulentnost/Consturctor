@echo off
cd /d "%~dp0"
set "BACKEND_URL=http://127.0.0.1:7812"
rem Docker often binds 5174 locally — use a free Vite port for Orchestrator.
if not defined ORCH_VITE_PORT set "ORCH_VITE_PORT=5176"
rem Use orchestrator/desktop (has reset_run_scratch), not sibling Consturctor/desktop.
set "CONSTRUCTOR_DESKTOP_ROOT=%~dp0..\..\desktop"
title Orchestrator
echo Starting Orchestrator Electron...
echo Backend: %BACKEND_URL%
echo Desktop: %CONSTRUCTOR_DESKTOP_ROOT%
echo Vite:    %ORCH_VITE_PORT%
npm run dev
if errorlevel 1 pause
