@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
echo === Smoke host tools (outside containers) ===
py -3.12 "%~dp0smoke_host_tools.py"
exit /b %ERRORLEVEL%
