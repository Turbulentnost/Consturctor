@echo off
cd /d "%~dp0"
echo Constructor Web UI: http://127.0.0.1:8780/
echo Backend proxy target: http://127.0.0.1:7812
set GATEWAY_URL=http://127.0.0.1:7812
start "" http://127.0.0.1:8780/
py -3.12 server.py
