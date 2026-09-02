@echo off
cd /d "%~dp0"
set "BACKEND_URL=http://192.168.1.157:7812"
title Orchestrator
echo Starting Orchestrator Electron...
echo Backend: %BACKEND_URL%
npm run dev
if errorlevel 1 pause
