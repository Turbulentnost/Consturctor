# Прямой маршрут к 1С в обход happ / AdGuard VPN.
# Публикация OData и HTTP документооборота: srv1.turbo-don.ru -> 192.168.2.229 (порт 81).
# SQL erp_pm: ii1.turbo-don.ru -> 192.168.1.157.
# Запуск от администратора:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\onec-direct-route.ps1
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$Targets = @(
  @{ Name = 'srv1.turbo-don.ru'; Ip = '192.168.2.229' },
  @{ Name = 'ii1.turbo-don.ru'; Ip = '192.168.1.157'; Alias = 'ii1' }
)
$Marker = '# constructor-onec-direct'

function Test-SameSubnet([string]$ip, [string]$nicIp, [int]$prefix) {
  $ipBytes = [Net.IPAddress]::Parse($ip).GetAddressBytes()
  $nicBytes = [Net.IPAddress]::Parse($nicIp).GetAddressBytes()
  [Array]::Reverse($ipBytes)
  [Array]::Reverse($nicBytes)
  $ipNum = [BitConverter]::ToUInt32($ipBytes, 0)
  $nicNum = [BitConverter]::ToUInt32($nicBytes, 0)
  $bits = ('1' * $prefix).PadRight(32, '0')
  $mask = [Convert]::ToUInt32($bits, 2)
  return (($ipNum -band $mask) -eq ($nicNum -band $mask))
}

$lan = Get-NetIPConfiguration | Where-Object {
  $_.NetAdapter.Status -eq 'Up' -and
  $_.InterfaceAlias -notmatch 'happ|AdGuard|vEthernet|WSL|Loopback|Default Switch' -and
  $_.IPv4Address
} | Select-Object -First 1
if (-not $lan) { throw 'Не найден сетевой адаптер локальной сети (Ethernet).' }

$nicIp = $lan.IPv4Address[0].IPAddress
$prefix = [int]$lan.IPv4Address[0].PrefixLength
$alias = $lan.InterfaceAlias
$gw = @($lan.IPv4DefaultGateway | Where-Object { $_.NextHop }) | Select-Object -First 1 -ExpandProperty NextHop
$localIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress)
Write-Host "Интерфейс: $alias  $nicIp/$prefix  шлюз: $(if ($gw) { $gw } else { 'нет' })"

$hostLines = @()
foreach ($target in $Targets) {
  $ip = $target.Ip
  $names = @($target.Name)
  if ($target.Alias) { $names += $target.Alias }
  Write-Host "$($names -join ', ') -> $ip"
  $hostLines += "$ip $($names -join ' ') $Marker"

  if ($localIps -contains $ip) {
    Write-Host "  $ip — адрес этого компьютера, отдельный маршрут не нужен."
    continue
  }

  $onLink = Test-SameSubnet $ip $nicIp $prefix
  $nextHop = '0.0.0.0'
  if (-not $onLink) {
    if (-not $gw) { throw "Адрес $ip не в подсети $nicIp/$prefix и у $alias нет шлюза." }
    $nextHop = $gw
  }
  Write-Host $(if ($onLink) { "  маршрут $ip/32 прямо в локальную сеть" } else { "  маршрут $ip/32 через $nextHop" })

  Get-NetRoute -DestinationPrefix "$ip/32" -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
  New-NetRoute -DestinationPrefix "$ip/32" -InterfaceAlias $alias -NextHop $nextHop -RouteMetric 1 -PolicyStore PersistentStore | Out-Null
}

$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$lines = @(Get-Content -Path $hostsPath -ErrorAction SilentlyContinue)
$kept = @($lines | Where-Object { $_ -notmatch [regex]::Escape($Marker) })
$kept += $hostLines
Set-Content -Path $hostsPath -Value $kept -Encoding ascii
Write-Host "hosts записан: srv1 и ii1 смотрят на свои IPv4, не на адреса happ."
Write-Host "Готово."
