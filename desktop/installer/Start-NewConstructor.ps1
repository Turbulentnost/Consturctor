#Requires -Version 5.1
param([switch]$Background)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Exe = Join-Path $Root "NewConstructor.exe"
$EnvFile = Join-Path $Root ".env"

function Read-EnvFile([string]$path) {
    $map = @{}
    if (-not (Test-Path $path)) { return $map }
    Get-Content $path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $i = $line.IndexOf("=")
        if ($i -lt 1) { return }
        $map[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim()
    }
    return $map
}

function Test-Backend([string]$url) {
    try {
        $u = $url.TrimEnd("/") + "/health"
        $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 2
        return $r.StatusCode -ge 200 -and $r.StatusCode -lt 500
    } catch {
        return $false
    }
}

$envMap = Read-EnvFile $EnvFile
$backendUrl = if ($envMap["BACKEND_URL"]) { $envMap["BACKEND_URL"] } else { "http://127.0.0.1:7812" }
$backendDir = $envMap["BACKEND_DIR"]
$autostart = ($envMap["BACKEND_AUTOSTART"] -eq "1")

if (-not (Test-Backend $backendUrl) -and $autostart -and $backendDir -and (Test-Path (Join-Path $backendDir "app\main.py"))) {
    Write-Host "Backend is down - starting..." -ForegroundColor Yellow
    $py = "C:\Users\a.komarkova\AppData\Local\Programs\Python\Python313\python.exe"
    $argList = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "7812")
    if (Test-Path $py) {
        Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $backendDir -WindowStyle Minimized
    } else {
        Start-Process -FilePath "py" -ArgumentList (@("-3.13") + $argList) -WorkingDirectory $backendDir -WindowStyle Minimized
    }
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Backend $backendUrl) { break }
    }
    if (-not (Test-Backend $backendUrl)) {
        Write-Host "Backend still unavailable. Check $backendDir" -ForegroundColor Red
    } else {
        Write-Host "Backend ready." -ForegroundColor Green
    }
}

if (-not (Test-Path $Exe)) {
    throw "Missing $Exe"
}
$extra = @()
if ($Background -or $args -contains "--background" -or $args -contains "-Background") {
    $extra += "--background"
}
Start-Process -FilePath $Exe -ArgumentList $extra -WorkingDirectory $Root
