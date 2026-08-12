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
if exist "scripts\desktop_tools.local.cmd" (
  echo Applying scripts\desktop_tools.local.cmd ...
  call "scripts\desktop_tools.local.cmd"
)
set "USE_STUBS=false"

echo FS_ROOT_ALLOWLIST=%FS_ROOT_ALLOWLIST%
echo SHELL_CWD_ROOTS=%SHELL_CWD_ROOTS%
echo.

start "platform-tool-com" cmd /k "cd /d %CD% && set API_PORT=7826&& set USE_STUBS=false&& py -3.12 -m platform_tool_com.main"
start "platform-tool-filesystem" cmd /k "cd /d %CD% && set API_PORT=7827&& set USE_STUBS=false&& set FS_ROOT_ALLOWLIST=%FS_ROOT_ALLOWLIST%&& py -3.12 -m platform_tool_filesystem.main"
start "platform-tool-shell-native" cmd /k "cd /d %CD% && set API_PORT=7828&& set USE_STUBS=false&& set SHELL_CWD_ROOTS=%SHELL_CWD_ROOTS%&& py -3.12 -m platform_tool_shell.native_main"

echo Desktop tools started in separate windows.
echo To allow extra folders for fs.* copy scripts\desktop_tools.local.cmd.example to desktop_tools.local.cmd
exit /b 0
