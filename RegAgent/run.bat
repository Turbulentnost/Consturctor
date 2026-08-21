@echo off
cd /d "%~dp0"
if not exist .venv (
  py -3.12 -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q
python main.py
if errorlevel 1 (
  echo.
  echo RegAgent завершился с ошибкой. Код: %ERRORLEVEL%
  pause
)
