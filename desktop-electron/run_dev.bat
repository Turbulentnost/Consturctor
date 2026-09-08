@echo off
cd /d "%~dp0"
set "BACKEND_URL=http://127.0.0.1:7812"
rem Constructor Vite port (5174 is often taken by Docker, Orchestrator uses 5176).
if not defined CONSTRUCTOR_VITE_PORT set "CONSTRUCTOR_VITE_PORT=5173"
title Constructor
echo Starting Constructor Electron...
echo Backend: %BACKEND_URL%
echo Vite:    %CONSTRUCTOR_VITE_PORT%
npm run dev
if errorlevel 1 pause
