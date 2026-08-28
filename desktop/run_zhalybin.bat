@echo off
cd /d "%~dp0"
set "QT_QPA_PLATFORM="
set "BACKEND_URL=http://127.0.0.1:7812"
set "CONSTRUCTOR_INSTANCE=zhalybin"
set "CONSTRUCTOR_TEST_USER=1"
set "AUTH_SKIP_LOGIN_PAGE=1"
echo Starting turbobot as Жалыбин Максим Дмитриевич...
py -3.12 main.py
if errorlevel 1 pause
