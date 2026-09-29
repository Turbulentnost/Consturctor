# Sets local dev keys in %APPDATA%\Orchestrator\.env (no secrets logged).
param(
  [string]$BackendUrl = 'http://127.0.0.1:7812',
  [string]$PreferLocal = '1'
)

$path = Join-Path $env:APPDATA 'Orchestrator\.env'
$dir = Split-Path $path -Parent
if (-not (Test-Path $dir)) {
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

$lines = @()
if (Test-Path $path) {
  $lines = Get-Content -Path $path -Encoding UTF8
}

function Set-EnvKey {
  param([string[]]$Lines, [string]$Key, [string]$Value)
  $out = New-Object System.Collections.Generic.List[string]
  $found = $false
  foreach ($raw in $Lines) {
    $t = $raw.TrimStart()
    if ($t -match "^\s*$([regex]::Escape($Key))\s*=") {
      $out.Add("$Key=$Value")
      $found = $true
    } else {
      $out.Add($raw)
    }
  }
  if (-not $found) {
    if ($out.Count -gt 0 -and $out[$out.Count - 1].Trim() -ne '') { $out.Add('') }
    $out.Add("$Key=$Value")
  }
  return $out.ToArray()
}

$lines = Set-EnvKey -Lines $lines -Key 'BACKEND_URL' -Value $BackendUrl
$lines = Set-EnvKey -Lines $lines -Key 'VITE_BACKEND_URL' -Value $BackendUrl
$lines = Set-EnvKey -Lines $lines -Key 'ORCH_PREFER_LOCAL' -Value $PreferLocal

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines($path, $lines, $utf8NoBom)
Write-Host "Roaming Orchestrator .env: BACKEND_URL=$BackendUrl ORCH_PREFER_LOCAL=$PreferLocal"
