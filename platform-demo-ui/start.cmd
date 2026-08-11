@echo off
cd /d "%~dp0"
echo.
echo NOTE: if Docker stack is running, use http://127.0.0.1:8790/ from compose.
echo       Do not run this script at the same time — port 8790 conflict.
echo.
echo Starting local demo UI proxy on http://127.0.0.1:8790/
start "" http://127.0.0.1:8790/
py -3.12 server.py
