@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "CONSTRUCTOR_ROOT=%CD%"

echo === Constructor: полный локальный запуск ===
echo.

echo [1/4] Docker stack (gateway + platform)...
pushd infra
docker compose up -d --build
if errorlevel 1 (
  popd
  echo ERROR: docker compose failed
  exit /b 1
)
popd
timeout /t 8 /nobreak >nul

echo.
echo [2/4] Desktop host :7830 + launcher :7829...
call "scripts\ensure_desktop_tools.cmd"
if errorlevel 1 echo WARNING: ensure_desktop_tools returned %ERRORLEVEL%

echo.
echo [3/4] 1C COM service :7831...
call "scripts\restart_onec_com_service.cmd"
if errorlevel 1 echo WARNING: COM service start failed

echo.
echo [4/4] Health check...
call "scripts\check_platform_health.cmd"
set "RC=%ERRORLEVEL%"

echo.
echo === Готово ===
echo   Gateway:  http://127.0.0.1:7812/health
echo   Desktop:  desktop\dist\NewConstructor.exe
echo   Запуск:   scripts\start_desktop_app.cmd
echo.
exit /b %RC%
