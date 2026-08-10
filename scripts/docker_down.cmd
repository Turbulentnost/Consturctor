@echo off
cd /d "%~dp0..\infra"
docker compose down
echo Stopped.
