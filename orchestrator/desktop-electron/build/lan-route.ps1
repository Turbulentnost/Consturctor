# Persistent route: 192.168.0.0/16 goes through the physical gateway, not the Happ TUN.
# The installer is elevated. A missing Happ install or a missing gateway must not fail the setup.
$ErrorActionPreference = 'Continue'
$logDir = Join-Path $env:ProgramData 'Orchestrator'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'lan-route.log'

function Write-Log([string]$Message) {
  Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message)
}

try {
  $adapters = @(Get-NetAdapter -ErrorAction SilentlyContinue)
  $happ = @($adapters | Where-Object {
      $_.Name -like 'happ-*' -or $_.InterfaceDescription -like '*Happ*'
    })
  $installed = $happ.Count -gt 0
  if (-not $installed) {
    $keys = @(
      'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
      'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
      'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    $app = Get-ItemProperty -Path $keys -ErrorAction SilentlyContinue |
      Where-Object { $_.DisplayName -like '*Happ*' } |
      Select-Object -First 1
    $installed = $null -ne $app
  }
  if (-not $installed) {
    $proc = Get-Process -ErrorAction SilentlyContinue |
      Where-Object { $_.ProcessName -like '*Happ*' } |
      Select-Object -First 1
    $svc = Get-Service -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -like '*Happ*' -or $_.DisplayName -like '*Happ*' } |
      Select-Object -First 1
    $installed = ($null -ne $proc) -or ($null -ne $svc)
  }
  if (-not $installed) {
    Write-Log 'Happ is not installed, route skipped'
    exit 0
  }

  $happNames = @($happ | ForEach-Object { $_.Name })
  # Happ often replaces 0.0.0.0/0, so the physical gateway lives on the NIC, not in the winning default route.
  $nic = Get-NetIPConfiguration -ErrorAction SilentlyContinue |
    Where-Object {
      $_.NetAdapter.Status -eq 'Up' -and
      $_.IPv4DefaultGateway -and
      $_.IPv4DefaultGateway.NextHop -and
      ($happNames -notcontains $_.InterfaceAlias) -and
      $_.InterfaceAlias -notlike 'happ-*' -and
      $_.InterfaceDescription -notlike '*Happ*' -and
      $_.InterfaceAlias -notlike 'vEthernet*'
    } |
    Select-Object -First 1
  if ($nic) {
    $lan = [pscustomobject]@{
      InterfaceAlias = $nic.InterfaceAlias
      NextHop = $nic.IPv4DefaultGateway.NextHop
    }
  } else {
    $lan = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -ErrorAction SilentlyContinue |
      Where-Object {
        $_.NextHop -and $_.NextHop -ne '0.0.0.0' -and ($happNames -notcontains $_.InterfaceAlias)
      } |
      Sort-Object RouteMetric, InterfaceMetric |
      Select-Object -First 1
  }
  if (-not $lan) {
    Write-Log 'Happ is present, but no physical default gateway was found'
    exit 0
  }

  $prefix = '192.168.0.0/16'
  $same = Get-NetRoute -DestinationPrefix $prefix -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.InterfaceAlias -eq $lan.InterfaceAlias -and $_.NextHop -eq $lan.NextHop } |
    Select-Object -First 1
  if ($same) {
    Write-Log ("route already set: {0} via {1} dev {2}" -f $prefix, $lan.NextHop, $lan.InterfaceAlias)
    exit 0
  }

  Get-NetRoute -DestinationPrefix $prefix -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue
  New-NetRoute -DestinationPrefix $prefix -InterfaceAlias $lan.InterfaceAlias -NextHop $lan.NextHop -RouteMetric 1 -PolicyStore PersistentStore -ErrorAction Stop | Out-Null
  Write-Log ("added {0} via {1} dev {2}" -f $prefix, $lan.NextHop, $lan.InterfaceAlias)
  exit 0
} catch {
  Write-Log ("failed: {0}" -f $_.Exception.Message)
  exit 0
}
