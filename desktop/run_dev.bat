@echo off
cd /d "%~dp0"
set "BACKEND_URL=http://192.168.2.135:7812"
py -3.12 main.py
if errorlevel 1 pause
