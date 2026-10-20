# Прямой маршрут к Exchange в обход happ / AdGuard VPN.
# Сервер: mail.turbo-don.ru и autodiscover.turbo-don.ru -> 192.168.1.129
# Запуск от администратора: powershell -NoProfile -ExecutionPolicy Bypass -File .\outlook-direct-route.ps1
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'

$MailName = 'mail.turbo-don.ru'
$AutoName = 'autodiscover.turbo-don.ru'
$FallbackIp = '192.168.1.129'

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

$resolved = $null
try {
  $resolved = Resolve-DnsName $MailName -Type A -DnsOnly -ErrorAction Stop |
    Where-Object { $_.IPAddress -match '^\d+\.\d+\.\d+\.\d+$' } |
    Select-Object -First 1 -ExpandProperty IPAddress
} catch {
  Write-Host "DNS A для $MailName не ответил, берём $FallbackIp"
}
if (-not $resolved) { $resolved = $FallbackIp }
Write-Host "Exchange IPv4: $resolved ($MailName)"

$aaaa = @()
try {
  $aaaa = @(Resolve-DnsName $MailName -Type AAAA -DnsOnly -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress } |
    Select-Object -ExpandProperty IPAddress)
} catch { }
if ($aaaa.Count) {
  Write-Host "DNS также отдал IPv6 (часто это подмена AdGuard/happ, не сам Exchange):"
  $aaaa | ForEach-Object { Write-Host "  $_" }
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
$onLink = Test-SameSubnet $resolved $nicIp $prefix
$nextHop = '0.0.0.0'
if (-not $onLink) {
  if (-not $gw) { throw "Адрес $resolved не в подсети $nicIp/$prefix и у $alias нет шлюза." }
  $nextHop = $gw
}
Write-Host "Интерфейс: $alias  $nicIp/$prefix  шлюз: $(if ($gw) { $gw } else { 'нет' })"
Write-Host $(if ($onLink) { "Маршрут: $resolved/32 прямо в локальную сеть" } else { "Маршрут: $resolved/32 через $nextHop" })

Get-NetRoute -DestinationPrefix "$resolved/32" -ErrorAction SilentlyContinue |
  Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue

$params = @{
  DestinationPrefix = "$resolved/32"
  InterfaceAlias    = $alias
  NextHop           = $nextHop
  RouteMetric       = 1
  PolicyStore       = 'PersistentStore'
}
New-NetRoute @params | Out-Null
Write-Host "Постоянный маршрут записан."

$hostsPath = Join-Path $env:SystemRoot 'System32\drivers\etc\hosts'
$marker = '# constructor-outlook-direct'
$lines = @(Get-Content -Path $hostsPath -ErrorAction SilentlyContinue)
$kept = @($lines | Where-Object { $_ -notmatch [regex]::Escape($marker) -and $_ -notmatch '^\s*#?\s*\d+\.\d+\.\d+\.\d+\s+(mail|autodiscover)\.turbo-don\.ru(\s|$)' })
$kept += "$resolved $MailName $AutoName $marker"
Set-Content -Path $hostsPath -Value $kept -Encoding ascii
Write-Host "hosts: $MailName и $AutoName -> $resolved (чтобы имя не ушло в IPv6 happ)."
Write-Host "Готово. Проверка: ping $resolved  и  Resolve-DnsName $MailName -Type A"
