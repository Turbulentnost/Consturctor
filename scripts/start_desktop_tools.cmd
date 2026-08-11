@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo Starting desktop tool services on Windows host...
echo   COM         http://127.0.0.1:7826
echo   Filesystem  http://127.0.0.1:7827
echo   Shell native http://127.0.0.1:7828
echo.

if not exist "data\filesystem" mkdir "data\filesystem" >nul 2>&1
if not exist "data\shell-native" mkdir "data\shell-native" >nul 2>&1

set "FS_ROOT_ALLOWLIST=%CD%\data\filesystem"
set "SHELL_CWD_ROOTS=%CD%\data\shell-native"
set "USE_STUBS=false"

start "platform-tool-com" cmd /k "cd /d %CD% && set API_PORT=7826&& py -3.12 -m platform_tool_com.main"
start "platform-tool-filesystem" cmd /k "cd /d %CD% && set API_PORT=7827&& py -3.12 -m platform_tool_filesystem.main"
start "platform-tool-shell-native" cmd /k "cd /d %CD% && set API_PORT=7828&& py -3.12 -m platform_tool_shell.native_main"

echo Desktop tools started in separate windows.
exit /b 0
