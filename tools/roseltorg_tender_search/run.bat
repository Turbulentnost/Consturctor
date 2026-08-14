@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   Поиск тендеров на Росэлторг (223-ФЗ)
echo ============================================================
echo.

REM --- 0. Готовый exe из desktop-дистрибутива: Python пользователю не нужен ---
if exist "%~dp0roseltorg_tender_search.exe" (
  if exist "%~dp0ms-playwright" set "PLAYWRIGHT_BROWSERS_PATH=%~dp0ms-playwright"
  echo [1/2] Запускаю встроенный инструмент поиска...
  "%~dp0roseltorg_tender_search.exe" run %* -o report.xlsx
  if errorlevel 1 (
    echo.
    echo [ОШИБКА] Поиск завершился с ошибкой. Смотрите сообщение выше.
    if not defined RTS_NONINTERACTIVE pause
    exit /b 1
  )
  if not defined RTS_NONINTERACTIVE (
    echo.
    echo [2/2] Открываю отчёт report.xlsx...
    if exist "report.xlsx" start "" "report.xlsx"
  )
  echo.
  echo Готово.
  if not defined RTS_NONINTERACTIVE pause
  endlocal
  exit /b 0
)

REM --- 1. Выбор интерпретатора Python ---
set "PY=py -3"
%PY% --version >nul 2>&1
if errorlevel 1 (
  set "PY=python"
  %PY% --version >nul 2>&1
  if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите Python 3.10+ с https://www.python.org/downloads/
    echo          и при установке отметьте "Add Python to PATH".
    if not defined RTS_NONINTERACTIVE pause
    exit /b 1
  )
)

REM --- 2. Виртуальное окружение (создаётся один раз) ---
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Создаю окружение и устанавливаю зависимости (только при первом запуске)...
  %PY% -m venv .venv
  call ".venv\Scripts\activate.bat"
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  python -m playwright install chromium
) else (
  call ".venv\Scripts\activate.bat"
)

REM --- 3. Запуск поиска ---
echo.
echo [2/3] Запускаю поиск. Это может занять несколько минут...
echo.
python -m roseltorg_tender_search run %* -o report.xlsx
if errorlevel 1 (
  echo.
  echo [ОШИБКА] Поиск завершился с ошибкой. Смотрите сообщение выше.
  if not defined RTS_NONINTERACTIVE pause
  exit /b 1
)

REM --- 4. Открыть отчёт (при ручном запуске; из приложения отчёт открывает само приложение) ---
if not defined RTS_NONINTERACTIVE (
  echo.
  echo [3/3] Открываю отчёт report.xlsx...
  if exist "report.xlsx" start "" "report.xlsx"
)

echo.
echo Готово.
if not defined RTS_NONINTERACTIVE pause
endlocal
