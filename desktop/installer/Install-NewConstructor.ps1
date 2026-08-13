#Requires -Version 5.1
param(
    [string]$SourceDir = "",
    [string]$BackendDir = "",
    [string]$BackendUrl = "http://127.0.0.1:7812",
    [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$msg) { Write-Host "-> $msg" -ForegroundColor Cyan }

if (-not $SourceDir) {
    $SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path (Join-Path $SourceDir "payload")) {
        $SourceDir = Join-Path $SourceDir "payload"
    }
}
$SourceDir = (Resolve-Path $SourceDir).Path
$exeSrc = Join-Path $SourceDir "NewConstructor.exe"
if (-not (Test-Path $exeSrc)) {
    throw "NewConstructor.exe not found in $SourceDir. Build desktop first (build_exe.bat)."
}

$installRoot = Join-Path $env:LOCALAPPDATA "NewConstructor"
Write-Step "Install to $installRoot"
New-Item -ItemType Directory -Force -Path $installRoot | Out-Null

Copy-Item -Force $exeSrc (Join-Path $installRoot "NewConstructor.exe")
foreach ($name in @(
    "Start-NewConstructor.cmd",
    "Start-NewConstructor.ps1",
    "Install-NewConstructor.ps1"
)) {
    $src = Join-Path $SourceDir $name
    if (Test-Path $src) {
        Copy-Item -Force $src (Join-Path $installRoot $name)
    }
}

if (-not $BackendDir) {
    $probe = @(
        (Join-Path $SourceDir "..\..\..\backend"),
        (Join-Path $SourceDir "..\..\backend"),
        "c:\Users\a.komarkova\Documents\projects\NewConstructor\backend"
    )
    foreach ($p in $probe) {
        try { $full = [System.IO.Path]::GetFullPath($p) } catch { continue }
        if (Test-Path (Join-Path $full "app\main.py")) {
            $BackendDir = $full
            break
        }
    }
}

$envLines = @("BACKEND_URL=$BackendUrl")
if ($BackendDir -and (Test-Path (Join-Path $BackendDir "app\main.py"))) {
    $envLines += "BACKEND_DIR=$BackendDir"
    $envLines += "BACKEND_AUTOSTART=1"
    Write-Step "Backend autostart: $BackendDir"
} else {
    $envLines += "BACKEND_AUTOSTART=0"
    Write-Step "Backend folder not found; server must already run at $BackendUrl"
}
$envLines | Set-Content -Encoding ASCII (Join-Path $installRoot ".env")

function New-Shortcut([string]$Path, [string]$Target, [string]$Args, [string]$WorkDir, [string]$Icon) {
    $w = New-Object -ComObject WScript.Shell
    $s = $w.CreateShortcut($Path)
    $s.TargetPath = $Target
    if ($Args) { $s.Arguments = $Args }
    $s.WorkingDirectory = $WorkDir
    if ($Icon -and (Test-Path $Icon)) { $s.IconLocation = $Icon }
    $s.Save()
}

if (-not $NoShortcuts) {
    $startCmd = Join-Path $installRoot "Start-NewConstructor.cmd"
    $exe = Join-Path $installRoot "NewConstructor.exe"
    $target = if (Test-Path $startCmd) { $startCmd } else { $exe }
    $desk = [Environment]::GetFolderPath("Desktop")
    $programs = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\NewConstructor"
    New-Item -ItemType Directory -Force -Path $programs | Out-Null
    Write-Step "Create Desktop and Start Menu shortcuts"
    New-Shortcut (Join-Path $desk "NewConstructor.lnk") $target "" $installRoot $exe
    New-Shortcut (Join-Path $programs "NewConstructor.lnk") $target "" $installRoot $exe
    New-Shortcut (Join-Path $programs "Uninstall NewConstructor.lnk") "powershell.exe" `
        "-NoProfile -ExecutionPolicy Bypass -File `"$installRoot\Uninstall-NewConstructor.ps1`"" $installRoot $exe
}

$uninstall = @'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desk = [Environment]::GetFolderPath("Desktop")
$programs = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\NewConstructor"
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desk "NewConstructor.lnk")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $programs
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $root
Write-Host "NewConstructor removed."
'@
Set-Content -Encoding ASCII (Join-Path $installRoot "Uninstall-NewConstructor.ps1") -Value $uninstall

Write-Host ""
Write-Host "OK. Use Desktop shortcut 'NewConstructor' or:" -ForegroundColor Green
Write-Host "  $installRoot\Start-NewConstructor.cmd"
Write-Host ""
