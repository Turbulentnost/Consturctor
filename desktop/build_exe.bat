@echo off
setlocal
cd /d "%~dp0"

set PY=C:\Users\mdj\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PY%" set PY=py -3.12

echo Using Python: %PY%
"%PY%" build_exe.py
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo BUILD FAILED (exit %ERR%)
  pause
)
exit /b %ERR%
