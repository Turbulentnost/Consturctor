@echo off
cd /d "%~dp0"
if not exist .venv (
  py -3.12 -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q
set "REGAGENT_STARTUP_LOG=%~dp0regagent_startup.log"
del /q "%REGAGENT_STARTUP_LOG%" 2>nul
pythonw main.py 1>>"%REGAGENT_STARTUP_LOG%" 2>&1
if errorlevel 1 (
  echo.
  echo RegAgent ?????????? ? ???????. ???: %ERRORLEVEL%
  if exist "%REGAGENT_STARTUP_LOG%" (
    echo --- regagent_startup.log ---
    type "%REGAGENT_STARTUP_LOG%"
    echo --- ????? ???? ---
  )
  echo ??? ??????? ? ????????: python main.py
  pause
)
