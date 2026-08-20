@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set DESKTOP_DIR=%~dp0..
set PAYLOAD=%~dp0payload
set OUT=%DESKTOP_DIR%\dist
set DESKTOP_OUT=%USERPROFILE%\Desktop\NewConstructor-Setup
set PY=py -3.12
set HOST_IP=192.168.2.91
set BACKEND_URL=http://192.168.2.91:7812
set AUTH_URL=http://192.168.2.91:7812

echo [1/5] Ensure NewConstructor.exe...
if not exist "%OUT%\NewConstructor.exe" (
  echo Building EXE...
  pushd "%DESKTOP_DIR%"
  call build_exe.bat
  popd
)
if not exist "%OUT%\NewConstructor.exe" (
  if exist "%USERPROFILE%\Desktop\NewConstructor.exe" (
    copy /Y "%USERPROFILE%\Desktop\NewConstructor.exe" "%OUT%\NewConstructor.exe" >nul
  )
)
if not exist "%OUT%\NewConstructor.exe" (
  echo ERROR: NewConstructor.exe not found. Run build_exe.bat first.
  exit /b 1
)

echo [2/5] Prepare payload...
if exist "%PAYLOAD%" rmdir /s /q "%PAYLOAD%"
mkdir "%PAYLOAD%"
copy /Y "%OUT%\NewConstructor.exe" "%PAYLOAD%\NewConstructor.exe" >nul
copy /Y "%~dp0Start-NewConstructor.ps1" "%PAYLOAD%\Start-NewConstructor.ps1" >nul
copy /Y "%~dp0Start-NewConstructor.cmd" "%PAYLOAD%\Start-NewConstructor.cmd" >nul
copy /Y "%~dp0Install-NewConstructor.ps1" "%PAYLOAD%\Install-NewConstructor.ps1" >nul
> "%PAYLOAD%\.env" echo HOST_IP=%HOST_IP%
>>"%PAYLOAD%\.env" echo BACKEND_URL=%BACKEND_URL%
>>"%PAYLOAD%\.env" echo AUTH_URL=%AUTH_URL%
> "%PAYLOAD%\README.txt" echo turbobot - установщик
>>"%PAYLOAD%\README.txt" echo.
>>"%PAYLOAD%\README.txt" echo 1. Запустите Установить.bat
>>"%PAYLOAD%\README.txt" echo 2. Войдите ФИО и пароль из erp_pm
>>"%PAYLOAD%\README.txt" echo.
>>"%PAYLOAD%\README.txt" echo Сервер: %BACKEND_URL%

echo [3/5] Create zip...
set ZIP=%OUT%\NewConstructor-Setup.zip
if exist "%ZIP%" del /f /q "%ZIP%"
powershell -NoProfile -Command "Compress-Archive -Path '%PAYLOAD%\*' -DestinationPath '%ZIP%' -Force"

echo [4/5] Write installer scripts...
> "%OUT%\Install-NewConstructor.cmd" echo @echo off
>>"%OUT%\Install-NewConstructor.cmd" echo chcp 65001 ^>nul
>>"%OUT%\Install-NewConstructor.cmd" echo setlocal
>>"%OUT%\Install-NewConstructor.cmd" echo set HERE=%%~dp0
>>"%OUT%\Install-NewConstructor.cmd" echo set WORK=%%TEMP%%\NewConstructor-Setup-%%RANDOM%%
>>"%OUT%\Install-NewConstructor.cmd" echo mkdir "%%WORK%%" ^>nul 2^>^&1
>>"%OUT%\Install-NewConstructor.cmd" echo powershell -NoProfile -Command "Expand-Archive -LiteralPath '%%HERE%%NewConstructor-Setup.zip' -DestinationPath '%%WORK%%' -Force"
>>"%OUT%\Install-NewConstructor.cmd" echo powershell -NoProfile -ExecutionPolicy Bypass -File "%%WORK%%\Install-NewConstructor.ps1" -SourceDir "%%WORK%%" -BackendUrl "%BACKEND_URL%" -AuthUrl "%AUTH_URL%" -HostIp "%HOST_IP%"
>>"%OUT%\Install-NewConstructor.cmd" echo pause

> "%PAYLOAD%\Установить.bat" echo @echo off
>>"%PAYLOAD%\Установить.bat" echo chcp 65001 ^>nul
>>"%PAYLOAD%\Установить.bat" echo cd /d "%%~dp0"
>>"%PAYLOAD%\Установить.bat" echo powershell -NoProfile -ExecutionPolicy Bypass -File "%%~dp0Install-NewConstructor.ps1" -SourceDir "%%~dp0" -BackendUrl "%BACKEND_URL%" -AuthUrl "%AUTH_URL%" -HostIp "%HOST_IP%"
>>"%PAYLOAD%\Установить.bat" echo pause

echo [5/5] Copy to Desktop\NewConstructor-Setup...
if exist "%DESKTOP_OUT%" rmdir /s /q "%DESKTOP_OUT%"
mkdir "%DESKTOP_OUT%"
xcopy /E /I /Y "%PAYLOAD%\*" "%DESKTOP_OUT%\" >nul
copy /Y "%ZIP%" "%DESKTOP_OUT%\NewConstructor-Setup.zip" >nul
copy /Y "%OUT%\Install-NewConstructor.cmd" "%DESKTOP_OUT%\Install-NewConstructor.cmd" >nul

echo.
echo Ready:
echo   %DESKTOP_OUT%
echo   %DESKTOP_OUT%\Ustanovit.bat  (Ustanovit.bat)
echo   %DESKTOP_OUT%\Install-NewConstructor.cmd
echo.
endlocal
