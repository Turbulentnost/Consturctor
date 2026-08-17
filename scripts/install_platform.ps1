# Platform packages and services — run from repo root (Consturctor/)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "Installing platform-contracts..."
py -3.12 -m pip install -e "$Root\platform-contracts"

Write-Host "Installing platform-db..."
py -3.12 -m pip install -e "$Root\platform-db"

Write-Host "Installing platform-service-common..."
py -3.12 -m pip install -e "$Root\platform-service-common"

Write-Host "Installing backend..."
py -3.12 -m pip install -e "$Root\backend"

$services = @(
    "platform-kpi",
    "platform-tool-imap",
    "platform-tool-onec",
    "platform-orchestrator",
    "platform-tool-shell",
    "platform-tool-browser"
)

foreach ($svc in $services) {
    Write-Host "Installing $svc..."
    py -3.12 -m pip install -e "$Root\services\$svc"
}

Write-Host "Installing test dependencies..."
py -3.12 -m pip install pytest httpx

Write-Host "Done."
