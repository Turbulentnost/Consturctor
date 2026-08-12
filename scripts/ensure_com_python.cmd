@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo === 1C COM: Python 32-bit + pywin32 ===
echo 1C client (1cv8c.exe) is 32-bit; COM requires matching Python bitness.
echo.

py -0p 2>nul | findstr /I /C:"-32" >nul
if errorlevel 1 (
  echo [1] 32-bit Python not found.
  echo     Download: https://www.python.org/downloads/windows/
  echo     Choose "Windows installer (32-bit)" for Python 3.12.x
  echo     Enable "Add python.exe to PATH" and "Install launcher for all users".
  echo.
  echo     Or try: winget install -e --id Python.Python.3.12 --architecture x86
  echo.
  pause
  exit /b 1
)

echo [1] Found 32-bit Python:
py -0p | findstr /I "-32"

echo [2] Install pywin32 for 32-bit Python ...
py -3.12-32 -m pip install --upgrade pip pywin32
if errorlevel 1 (
  echo ERROR: pip install failed. Try: py -3.12-32 -m ensurepip
  exit /b 1
)

echo [3] Install platform-tool-com + platform-tool-onec-com into 32-bit env ...
py -3.12-32 -m pip install -e "services\platform-tool-com[windows]"
py -3.12-32 -m pip install -e "services\platform-tool-onec-com[windows]"
if errorlevel 1 exit /b 1

echo [3] Install platform-tool-onec-com (32-bit) ...
py -3.12-32 -m pip install -e "services\platform-tool-onec-com[windows]"
if errorlevel 1 exit /b 1

echo.
echo OK. Start 1C COM service: scripts\start_onec_com_service.cmd
echo Test: py scripts\smoke_host_tools.py  (or com.onec.status via sandbox)
exit /b 0
