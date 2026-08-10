# Smoke demo: infra + stub services (requires Docker for PG/RabbitMQ optional)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "Starting PostgreSQL + RabbitMQ..."
Push-Location "$Root\infra"
docker compose up -d postgres rabbitmq
Pop-Location

Write-Host "Waiting for PostgreSQL..."
Start-Sleep -Seconds 8

$env:USE_STUBS = "true"
$env:DATABASE_URL = "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor"

Write-Host "Run services in separate terminals:"
Write-Host "  python -m platform_kpi.main"
Write-Host "  python -m platform_tool_imap.main"
Write-Host "  python -m platform_tool_onec.main"
Write-Host "  python -m platform_orchestrator.api_main"
Write-Host "  celery -A platform_orchestrator.celery_app worker -Q default,imap,onec,shell,browser -l info"
Write-Host "  python -m platform_tool_shell.main"
Write-Host "  python -m platform_tool_browser.main"
Write-Host "  python -m app.main   (from backend/)"

Write-Host "Smoke test (contracts):"
Push-Location $Root
py -3.12 -m pytest tests/test_platform_contracts.py tests/test_platform_tools_stub.py -q
Pop-Location
