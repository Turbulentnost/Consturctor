@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set PY=%~dp0.venv\Scripts\python.exe
) else (
  set PY=py -3.12
)

echo Using Python: %PY%
"%PY%" -m pip install -q pyinstaller
"%PY%" -m PyInstaller --noconfirm --clean RegAgent.spec
set ERR=%ERRORLEVEL%
if %ERR% neq 0 (
  echo.
  echo BUILD FAILED (exit %ERR%)
  exit /b %ERR%
)
echo.
echo Built: dist\RegAgent.exe
exit /b 0
