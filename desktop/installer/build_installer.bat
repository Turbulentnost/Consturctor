@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set DESKTOP=%~dp0..
set PAYLOAD=%~dp0payload
set OUT=%DESKTOP%\dist
set PY=C:\Users\a.komarkova\AppData\Local\Programs\Python\Python313\python.exe
if not exist "%PY%" set PY=py -3.13

echo [1/4] Ensure desktop EXE exists...
if not exist "%OUT%\NewConstructor.exe" (
  echo Building EXE first...
  pushd "%DESKTOP%"
  call build_exe.bat
  popd
)
if not exist "%OUT%\NewConstructor.exe" (
  echo ERROR: dist\NewConstructor.exe not found
  exit /b 1
)

echo [2/4] Prepare payload...
if exist "%PAYLOAD%" rmdir /s /q "%PAYLOAD%"
mkdir "%PAYLOAD%"
copy /Y "%OUT%\NewConstructor.exe" "%PAYLOAD%\NewConstructor.exe" >nul
copy /Y "%~dp0Start-NewConstructor.ps1" "%PAYLOAD%\Start-NewConstructor.ps1" >nul
copy /Y "%~dp0Start-NewConstructor.cmd" "%PAYLOAD%\Start-NewConstructor.cmd" >nul
copy /Y "%~dp0Install-NewConstructor.ps1" "%PAYLOAD%\Install-NewConstructor.ps1" >nul

echo [3/4] Create zip package...
set ZIP=%OUT%\NewConstructor-Setup.zip
if exist "%ZIP%" del /f /q "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path '%PAYLOAD%\*' -DestinationPath '%ZIP%' -Force"

echo [4/4] Write Install-NewConstructor.cmd...
> "%OUT%\Install-NewConstructor.cmd" echo @echo off
>>"%OUT%\Install-NewConstructor.cmd" echo setlocal
>>"%OUT%\Install-NewConstructor.cmd" echo set HERE=%%~dp0
>>"%OUT%\Install-NewConstructor.cmd" echo set WORK=%%TEMP%%\NewConstructor-Setup-%%RANDOM%%
>>"%OUT%\Install-NewConstructor.cmd" echo mkdir "%%WORK%%" ^>nul 2^>^&1
>>"%OUT%\Install-NewConstructor.cmd" echo echo Extracting...
>>"%OUT%\Install-NewConstructor.cmd" echo powershell -NoProfile -Command "Expand-Archive -LiteralPath '%%HERE%%NewConstructor-Setup.zip' -DestinationPath '%%WORK%%' -Force"
>>"%OUT%\Install-NewConstructor.cmd" echo if errorlevel 1 ^( echo Failed to extract zip. ^& pause ^& exit /b 1 ^)
>>"%OUT%\Install-NewConstructor.cmd" echo powershell -NoProfile -ExecutionPolicy Bypass -File "%%WORK%%\Install-NewConstructor.ps1" -SourceDir "%%WORK%%"
>>"%OUT%\Install-NewConstructor.cmd" echo echo.
>>"%OUT%\Install-NewConstructor.cmd" echo pause

echo.
echo Installer ready:
echo   %OUT%\Install-NewConstructor.cmd
echo   %OUT%\NewConstructor-Setup.zip
echo.
echo Already installed for this user:
echo   %%LOCALAPPDATA%%\NewConstructor
echo   Desktop shortcut: NewConstructor
echo.
endlocal
