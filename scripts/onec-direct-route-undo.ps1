# Снимает маршруты к 1С и строки hosts, которые добавил onec-direct-route.ps1.
# Запуск от администратора:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\onec-direct-route-undo.ps1
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$Ips = @('192.168.2.229', '192.168.1.157')
foreach ($ip in $Ips) {
  $routes = @(Get-NetRoute -DestinationPrefix "$ip/32" -PolicyStore PersistentStore -ErrorAction SilentlyContinue)
  $routes += @(Get-NetRoute -DestinationPrefix "$ip/32" -ErrorAction SilentlyContinue)
  foreach ($route in ($routes | Select-Object -Unique)) {
    if ($route.InterfaceAlias -match 'happ|AdGuard') { continue }
    Remove-NetRoute -InputObject $route -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Удалён маршрут $($route.DestinationPrefix) через $($route.InterfaceAlias)"
  }
}

$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$marker = '# constructor-onec-direct'
if (Test-Path $hostsPath) {
  $lines = @(Get-Content -Path $hostsPath)
  $kept = @($lines | Where-Object { $_ -notmatch [regex]::Escape($marker) })
  if ($kept.Count -ne $lines.Count) {
    Set-Content -Path $hostsPath -Value $kept -Encoding ascii
    Write-Host "Строки hosts для 1С сняты."
  }
}
Write-Host "Готово."
