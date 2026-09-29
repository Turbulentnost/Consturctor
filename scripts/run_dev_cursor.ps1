# Запуск backend + desktop в текущем терминале Cursor (без отдельных окон cmd).
param(
  [switch]$SkipPatch
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Root 'backend'
$Desktop = Join-Path $Root 'orchestrator\desktop-electron'
$LiveUrl = 'http://127.0.0.1:7812/health/live'

if (-not $SkipPatch) {
  & (Join-Path $Root 'scripts\patch_orchestrator_roaming_local.ps1')
  if ($LASTEXITCODE -ne 0) { throw 'patch_orchestrator_roaming_local.ps1 failed' }
}

function Test-BackendLive {
  try {
    $r = Invoke-WebRequest -UseBasicParsing $LiveUrl -TimeoutSec 1
    return ($r.StatusCode -eq 200)
  } catch {
    return $false
  }
}

$backendProc = $null
$weStartedBackend = $false
try {
  if (-not (Test-BackendLive)) {
    Write-Host '[cursor-dev] Starting backend (no port kill, no /health ERP ping)...' -ForegroundColor Cyan
    $env:AUTH_SKIP_SESSION_LOCK = '1'
    $backendProc = Start-Process -FilePath 'py' -ArgumentList @('-3.12', '-m', 'app.main') `
      -WorkingDirectory $Backend -WindowStyle Hidden -PassThru
    $weStartedBackend = $true
    Start-Sleep -Seconds 2
  } else {
    Write-Host '[cursor-dev] Backend already listening on :7812' -ForegroundColor Green
  }

  $env:BACKEND_URL = 'http://127.0.0.1:7812'
  $env:VITE_BACKEND_URL = $env:BACKEND_URL
  if (-not $env:ORCH_VITE_PORT) { $env:ORCH_VITE_PORT = '5176' }
  $env:ORCH_PREFER_LOCAL = '1'
  $env:ORCH_NO_BACKEND_SPAWN = '1'
  $env:ORCH_DEV_QUIET = '1'
  $env:ORCH_CONSOLE_NOTIFY = '1'
  $env:ORCH_IN_CURSOR = '1'
  $env:CONSTRUCTOR_DESKTOP_ROOT = Join-Path $Root 'desktop'
  $env:ORCH_BACKEND_ROOT = $Backend

  Set-Location $Desktop
  Write-Host '[cursor-dev] Electron + Vite — ERP checks only when you use 1C features.' -ForegroundColor Cyan
  npm run dev
} finally {
  if ($weStartedBackend -and $backendProc -and -not $backendProc.HasExited) {
    Write-Host '[cursor-dev] Background backend still on :7812.' -ForegroundColor DarkGray
  }
}
