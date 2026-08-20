#Requires -Version 5.1
param(
    [string]$SourceDir = "",
    [string]$BackendUrl = "http://192.168.2.91:7812",
    [string]$AuthUrl = "http://192.168.2.91:7812",
    [string]$HostIp = "192.168.2.91",
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
    throw "NewConstructor.exe not found in $SourceDir."
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

$envTemplate = Join-Path $SourceDir ".env"
if (Test-Path $envTemplate) {
    Copy-Item -Force $envTemplate (Join-Path $installRoot ".env")
    Write-Step "Config from bundled .env"
} else {
    $auth = if ($AuthUrl) { $AuthUrl.TrimEnd("/") } else { $BackendUrl.TrimEnd("/") }
    @(
        "HOST_IP=$HostIp",
        "BACKEND_URL=$($BackendUrl.TrimEnd('/'))",
        "AUTH_URL=$auth"
    ) | Set-Content -Encoding UTF8 (Join-Path $installRoot ".env")
    Write-Step "Config: BACKEND_URL=$BackendUrl AUTH_URL=$auth"
}

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

$exe = Join-Path $installRoot "NewConstructor.exe"
$startCmd = Join-Path $installRoot "Start-NewConstructor.cmd"
$runValue = if (Test-Path $startCmd) {
    "`"$startCmd`" --background"
} else {
    "`"$exe`" --background"
}
Write-Step "Register Windows startup"
New-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "NewConstructor" -Value $runValue -PropertyType String -Force | Out-Null

$uninstall = @'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$desk = [Environment]::GetFolderPath("Desktop")
$programs = Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs\NewConstructor"
Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "NewConstructor" -ErrorAction SilentlyContinue
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $desk "NewConstructor.lnk")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $programs
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $root
Write-Host "NewConstructor removed."
'@
Set-Content -Encoding ASCII (Join-Path $installRoot "Uninstall-NewConstructor.ps1") -Value $uninstall

Write-Host ""
Write-Host "OK. turbobot installed." -ForegroundColor Green
Write-Host "  Server: $BackendUrl"
Write-Host "  Launch: $installRoot\Start-NewConstructor.cmd"
Write-Host ""
