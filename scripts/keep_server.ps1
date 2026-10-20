# Поднимает Docker, Postgres конструктора и backend на :7812, если они погасли.
# Задача ConstructorServerKeepalive вызывает этот скрипт при входе и каждые 2 минуты.
$ErrorActionPreference = 'Continue'

$Root = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Root 'backend'
$LogDir = Join-Path $Backend 'logs'
$LogFile = Join-Path $LogDir 'keep-server.log'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-KeepLog([string]$Message) {
  $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
  Add-Content -Path $LogFile -Value $line -Encoding utf8
}

function Test-DockerEngine {
  docker info --format '{{.ServerVersion}}' 1>$null 2>$null
  return ($LASTEXITCODE -eq 0)
}

if (-not (Test-DockerEngine)) {
  $docker = Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue
  if (-not $docker) {
    Write-KeepLog 'Docker engine down, starting Docker Desktop'
    Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
  } else {
    Write-KeepLog 'Docker Desktop process is up, engine not ready yet'
  }
  exit 0
}

$pg = docker inspect -f '{{.State.Running}}' constructor-pg 2>$null
if ($pg -ne 'true') {
  Write-KeepLog 'starting constructor-pg'
  docker start constructor-pg 1>$null 2>$null
}

$listening = Get-NetTCPConnection -LocalPort 7812 -State Listen -ErrorAction SilentlyContinue
if ($listening) { exit 0 }

$starting = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -match 'app\.main' }
if ($starting) {
  Write-KeepLog 'backend process exists but :7812 is not listening yet'
  exit 0
}

Write-KeepLog 'starting backend on :7812'
$env:PYTHONPATH = $Backend
$env:PYTHONIOENCODING = 'utf-8'
Start-Process -FilePath 'py' -ArgumentList @('-3.12', '-m', 'app.main') `
  -WorkingDirectory $Backend -WindowStyle Hidden
