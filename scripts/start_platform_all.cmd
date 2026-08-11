@echo off
setlocal EnableExtensions

rem Docker stack + Windows desktop tools (COM, filesystem, native shell)
call "%~dp0docker_up.cmd"
if errorlevel 1 exit /b 1
call "%~dp0start_desktop_tools.cmd"
exit /b 0
