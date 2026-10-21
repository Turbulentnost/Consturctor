# Прямой маршрут к 1С и файловой шаре в обход happ / AdGuard VPN.
# Публикация OData и HTTP документооборота: srv1.turbo-don.ru -> 192.168.2.229 (порт 81).
# SQL erp_pm: ii1.turbo-don.ru -> 192.168.1.157.
# Файлы: \\192.168.1.198\Files.
# Запуск от администратора:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\onec-direct-route.ps1
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$Targets = @(
  @{ Name = 'srv1.turbo-don.ru'; Ip = '192.168.2.229' },
  @{ Name = 'ii1.turbo-don.ru'; Ip = '192.168.1.157'; Alias = 'ii1' },
  @{ Ip = '192.168.1.198' }
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
$ifIndex = [int]$lan.InterfaceIndex
$gw = @($lan.IPv4DefaultGateway | Where-Object { $_.NextHop }) | Select-Object -First 1 -ExpandProperty NextHop
$localIps = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress)
Write-Host "Интерфейс: $alias  $nicIp/$prefix  шлюз: $(if ($gw) { $gw } else { 'нет' })"

$hostLines = @()
foreach ($target in $Targets) {
  $ip = $target.Ip
  $names = @()
  if ($target.Name) { $names += $target.Name }
  if ($target.Alias) { $names += $target.Alias }
  if ($names.Count) {
    Write-Host "$($names -join ', ') -> $ip"
    $hostLines += "$ip $($names -join ' ') $Marker"
  } else {
    Write-Host "$ip (прямой адрес, без записи в hosts)"
  }

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

  # New-NetRoute -PolicyStore PersistentStore на этой Windows возвращает ошибку 87
  # и после Remove-NetRoute оставляет адрес без маршрута. route -p пишет активный и постоянный.
  Get-NetRoute -DestinationPrefix "$ip/32" -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceAlias -notmatch 'happ|AdGuard' } |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
  & route.exe -p delete $ip mask 255.255.255.255 | Out-Null
  & route.exe -p add $ip mask 255.255.255.255 $nextHop metric 1 if $ifIndex | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Не удалось добавить маршрут $ip/32 (route.exe $LASTEXITCODE)." }
}

$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$lines = @(Get-Content -Path $hostsPath -ErrorAction SilentlyContinue)
$kept = @($lines | Where-Object { $_ -notmatch [regex]::Escape($Marker) })
$kept += $hostLines
Set-Content -Path $hostsPath -Value $kept -Encoding ascii
Write-Host "hosts записан: srv1 и ii1 смотрят на свои IPv4, не на адреса happ. 192.168.1.198 идёт напрямую по /32."
Write-Host "Готово."
