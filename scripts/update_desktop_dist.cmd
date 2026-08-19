@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo Updating dist\ConstructorDesktop from latest build...
if not exist "dist\ConstructorDesktop\ConstructorDesktop.exe" (
  echo Run: py -3.12 desktop\build_exe.py
  exit /b 1
)

copy /Y "desktop\.env.example" "dist\ConstructorDesktop\.env" >nul 2>nul
if exist "desktop\.env" copy /Y "desktop\.env" "dist\ConstructorDesktop\.env" >nul

echo OK. Start: dist\ConstructorDesktop\ConstructorDesktop.exe
echo AUTH_URL must point to shared server, BACKEND_URL to 127.0.0.1:7812
exit /b 0
