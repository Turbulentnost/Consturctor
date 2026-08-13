@echo off
setlocal
cd /d "%~dp0"

set PY=C:\Users\a.komarkova\AppData\Local\Programs\Python\Python313\python.exe
if not exist "%PY%" set PY=py -3.13

echo [1/3] Installing build deps...
"%PY%" -m pip install -q --upgrade pip
"%PY%" -m pip install -q -r requirements.txt pyinstaller
if errorlevel 1 goto :err

echo [2/3] Building NewConstructor.exe (onefile)...
"%PY%" -m PyInstaller --noconfirm --clean NewConstructor.spec
if errorlevel 1 goto :err

if not exist "dist\.env" (
  if exist ".env" copy /Y ".env" "dist\.env" >nul
  if not exist "dist\.env" if exist ".env.example" copy /Y ".env.example" "dist\.env" >nul
)

echo [3/3] Done.
echo EXE: %cd%\dist\NewConstructor.exe
echo Put/edit dist\.env with BACKEND_URL=http://127.0.0.1:7812
echo Backend must be running separately.
goto :eof

:err
echo BUILD FAILED
exit /b 1
