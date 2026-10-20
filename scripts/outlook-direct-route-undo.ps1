# Снимает прямой маршрут к Exchange и строки hosts, которые добавил outlook-direct-route.ps1.
# Запуск от администратора: powershell -NoProfile -ExecutionPolicy Bypass -File .\outlook-direct-route-undo.ps1
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$FallbackIp = '192.168.1.129'
$ips = @($FallbackIp)
try {
  $fromDns = Resolve-DnsName mail.turbo-don.ru -Type A -DnsOnly -ErrorAction Stop |
    Where-Object { $_.IPAddress -match '^\d+\.\d+\.\d+\.\d+$' } |
    Select-Object -ExpandProperty IPAddress
  $ips += @($fromDns)
} catch { }
$ips = @($ips | Select-Object -Unique)

foreach ($ip in $ips) {
  $routes = @(Get-NetRoute -DestinationPrefix "$ip/32" -PolicyStore PersistentStore -ErrorAction SilentlyContinue)
  $routes += @(Get-NetRoute -DestinationPrefix "$ip/32" -ErrorAction SilentlyContinue)
  foreach ($route in ($routes | Select-Object -Unique)) {
    Remove-NetRoute -InputObject $route -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Удалён маршрут $($route.DestinationPrefix) через $($route.InterfaceAlias)"
  }
}

$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$marker = '# constructor-outlook-direct'
if (Test-Path $hostsPath) {
  $lines = @(Get-Content -Path $hostsPath)
  $kept = @($lines | Where-Object { $_ -notmatch [regex]::Escape($marker) })
  if ($kept.Count -ne $lines.Count) {
    Set-Content -Path $hostsPath -Value $kept -Encoding ascii
    Write-Host "Строка hosts снята."
  }
}
Write-Host "Готово."
