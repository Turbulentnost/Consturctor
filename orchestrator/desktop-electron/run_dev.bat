@echo off
cd /d "%~dp0"
if not defined BACKEND_URL set "BACKEND_URL=http://127.0.0.1:7812"
if not defined VITE_BACKEND_URL set "VITE_BACKEND_URL=%BACKEND_URL%"
rem Orchestrator Vite (5174 is often taken by Docker).
if not defined ORCH_VITE_PORT set "ORCH_VITE_PORT=5176"
title Orchestrator
echo Starting Orchestrator Electron...
echo Backend: %BACKEND_URL%
echo Vite:    %ORCH_VITE_PORT%
echo LAN gateway: set BACKEND_URL=http://192.168.1.157:7812
echo Local backend + 1C SOAP: run_dev_local.bat
npm run dev
if errorlevel 1 pause
