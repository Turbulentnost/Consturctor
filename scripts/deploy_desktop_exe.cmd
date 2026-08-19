@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "SRC=%CD%\desktop\dist\NewConstructor.exe"
set "DST=%USERPROFILE%\Desktop\NewConstructor.exe"
set "ENV=%USERPROFILE%\Desktop\.env"

if not exist "%SRC%" (
  echo ERROR: build first — py -3.12 desktop\build_exe.py
  exit /b 1
)

echo Deploying NewConstructor.exe to Desktop...
copy /Y "%SRC%" "%DST%" >nul
if errorlevel 1 (
  echo ERROR: failed to copy exe to %DST%
  exit /b 1
)

echo BACKEND_URL=http://127.0.0.1:7812> "%ENV%"
echo Wrote %ENV%

echo Checking COM :7831...
call "%~dp0restart_onec_com_service.cmd"

echo.
echo OK: %DST%
echo     Server: http://127.0.0.1:7812
echo     Re-login in the app if agent still fails.
exit /b 0
