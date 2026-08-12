@echo off
setlocal EnableExtensions

rem Docker stack + desktop launcher on Windows host (tools :7826-7828 start on agent invoke)
call "%~dp0docker_up.cmd"
if errorlevel 1 exit /b 1
call "%~dp0start_desktop_launcher.cmd"
if errorlevel 1 exit /b 1
exit /b 0
