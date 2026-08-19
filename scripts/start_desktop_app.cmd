@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

set "EXE=%CD%\desktop\dist\NewConstructor.exe"
if not exist "%EXE%" (
  echo EXE not found: %EXE%
  echo Run: py -3.12 desktop\build_exe.py  OR  desktop\build_exe.bat
  exit /b 1
)

if not exist "%CD%\desktop\dist\.env" (
  echo BACKEND_URL=http://127.0.0.1:7812> "%CD%\desktop\dist\.env"
)

echo Checking COM :7831...
call "scripts\restart_onec_com_service.cmd"
if errorlevel 1 (
  echo WARNING: COM service not ready — SMART/поручения из 1С не будут работать
)

call "scripts\deploy_desktop_exe.cmd"
if errorlevel 1 (
  echo WARNING: deploy to Desktop failed — starting from dist only
  set "EXE=%CD%\desktop\dist\NewConstructor.exe"
  start "" "%EXE%"
  exit /b 0
)

echo Starting Desktop\NewConstructor.exe
start "" "%USERPROFILE%\Desktop\NewConstructor.exe"
exit /b 0
