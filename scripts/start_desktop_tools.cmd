@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."

rem Manual / ops only — agent normally starts ports on demand via launcher :7829
echo Manual start of desktop tool services on Windows host...
if not exist "data\filesystem" mkdir "data\filesystem" >nul 2>&1
if not exist "data\shell-native" mkdir "data\shell-native" >nul 2>&1

set "FS_ROOT_ALLOWLIST=%CD%\data\filesystem"
set "SHELL_CWD_ROOTS=%CD%\data\shell-native"
if exist "scripts\desktop_tools.local.cmd" (
  echo Applying scripts\desktop_tools.local.cmd ...
  call "scripts\desktop_tools.local.cmd"
)
set "USE_STUBS=false"

set "STARTED=0"
set "SKIPPED=0"

call :maybe_start 7826 com platform_tool_com.main ""
call :maybe_start 7827 fs platform_tool_filesystem.main "FS_ROOT_ALLOWLIST=%FS_ROOT_ALLOWLIST%"
call :maybe_start 7828 shell platform_tool_shell.native_main "SHELL_CWD_ROOTS=%SHELL_CWD_ROOTS%"

echo.
if "%STARTED%"=="0" if not "%SKIPPED%"=="0" (
  echo Desktop tools already running ^(%SKIPPED%/3^).
) else (
  echo Desktop tools: started %STARTED%, already up %SKIPPED%/3.
  if not "%STARTED%"=="0" echo Logs: logs\desktop-*.out.log / logs\desktop-*.err.log
)
if /I "%DESKTOP_TOOLS_DEBUG%"=="1" (
  echo Debug mode: visible consoles enabled ^(DESKTOP_TOOLS_DEBUG=1^).
)
echo To allow extra folders for fs.* copy scripts\desktop_tools.local.cmd.example to desktop_tools.local.cmd
exit /b 0

:maybe_start
set "PORT=%~1"
set "TAG=%~2"
set "MODULE=%~3"
set "EXTRA_ENV=%~4"
call :port_up %PORT%
if not errorlevel 1 (
  echo [skip] port %PORT% ^(%TAG%^) already listening
  set /a SKIPPED+=1
  exit /b 0
)
echo [start] port %PORT% ^(%TAG%^) ...
if /I "%DESKTOP_TOOLS_DEBUG%"=="1" (
  if defined EXTRA_ENV (
    start "platform-tool-%TAG%" /MIN cmd /k "cd /d %CD% && set API_PORT=%PORT%&& set USE_STUBS=false&& set %EXTRA_ENV%&& py -3.12 -m %MODULE%"
  ) else (
    start "platform-tool-%TAG%" /MIN cmd /k "cd /d %CD% && set API_PORT=%PORT%&& set USE_STUBS=false&& py -3.12 -m %MODULE%"
  )
) else (
  powershell -NoProfile -Command ^
    "$wd='%CD%'; $tag='%TAG%'; $port='%PORT%'; $module='%MODULE%'; $extra='%EXTRA_ENV%';" ^
    "$cmd='set API_PORT='+$port+'&& set USE_STUBS=false'; if($extra){$cmd+='&& set '+$extra};" ^
    "$cmd+='&& py -3.12 -m '+$module;" ^
    "Start-Process cmd.exe -ArgumentList @('/c',$cmd) -WorkingDirectory $wd -WindowStyle Hidden -RedirectStandardOutput (Join-Path $wd ('logs\desktop-'+$tag+'.out.log')) -RedirectStandardError (Join-Path $wd ('logs\desktop-'+$tag+'.err.log')) | Out-Null"
)
set /a STARTED+=1
exit /b 0

:port_up
powershell -NoProfile -Command ^
  "$r=Test-NetConnection -ComputerName 127.0.0.1 -Port %1 -WarningAction SilentlyContinue; if ($r.TcpTestSucceeded) { exit 0 } else { exit 1 }"
exit /b %ERRORLEVEL%
