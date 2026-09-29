@echo off
cd /d "%~dp0.."
echo Redis for orchestrator: host port 6382 -^> container 6379
docker compose up -d constructor-redis
if errorlevel 1 (
  echo.
  echo Docker недоступен. Запустите Docker Desktop и повторите, либо установите Redis на :6382.
  echo REDIS_URL=redis://127.0.0.1:6382/0
  exit /b 1
)
docker compose ps constructor-redis
echo OK. REDIS_URL=redis://127.0.0.1:6382/0
