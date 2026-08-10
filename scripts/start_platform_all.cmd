@echo off
setlocal EnableExtensions

rem Legacy wrapper — full stack now runs in Docker Compose.
call "%~dp0docker_up.cmd"
exit /b %ERRORLEVEL%
