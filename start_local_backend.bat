@echo off
cd /d "%~dp0"
echo Starting Redis and RabbitMQ...
docker compose up -d constructor-redis constructor-rabbit
if errorlevel 1 (
  echo Docker extras failed. Backend will start anyway.
)
echo Starting constructor backend on http://192.168.2.91:7812 ...
cd /d "%~dp0backend"
py -3.12 -m app.main
if errorlevel 1 pause
