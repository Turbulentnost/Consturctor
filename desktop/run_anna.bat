@echo off
cd /d "%~dp0"
set "BACKEND_URL=http://192.168.1.157:7812"
set "CONSTRUCTOR_INSTANCE=anna"
set "CONSTRUCTOR_TEST_USER=1"
set "AUTH_SKIP_LOGIN_PAGE=1"
py -3.12 main.py
if errorlevel 1 pause
