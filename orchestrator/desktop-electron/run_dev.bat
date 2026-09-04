@echo off
cd /d "%~dp0"
set "BACKEND_URL=http://127.0.0.1:7812"
rem Use orchestrator/desktop (has reset_run_scratch), not sibling Consturctor/desktop.
set "CONSTRUCTOR_DESKTOP_ROOT=%~dp0..\..\desktop"
title Orchestrator
echo Starting Orchestrator Electron...
echo Backend: %BACKEND_URL%
echo Desktop: %CONSTRUCTOR_DESKTOP_ROOT%
npm run dev
if errorlevel 1 pause
