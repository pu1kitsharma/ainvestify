#Requires -Version 5.1
#Requires -RunAsAdministrator
<# Temporary synthetic probe only. Removes its exact firewall rule after 110s. #>
param(
    [Parameter(Mandatory=$true)][string]$Address,
    [Parameter(Mandatory=$true)][int]$ProbeProcessId,
    [Parameter(Mandatory=$true)][string]$Token
)
$ErrorActionPreference='Stop'
if ($Token -notmatch '^[0-9a-f]{32}$') { throw 'Invalid probe token' }
$addressObject=[System.Net.IPAddress]::Parse($Address)
if ($addressObject.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetworkV6 -or $addressObject.IsIPv6LinkLocal) { throw 'Require global IPv6' }
$networkAddress=Get-NetIPAddress -IPAddress $Address -AddressFamily IPv6 -ErrorAction Stop
$probe=Get-CimInstance Win32_Process -Filter ('ProcessId='+$ProbeProcessId)
$probeScript=(Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../scripts/probe_inbound_ipv6.py')).Path
if (-not $probe -or $probe.Name -ne 'python.exe' -or $probe.CommandLine -notmatch [regex]::Escape($probeScript) -or $probe.CommandLine -notmatch $Token) { throw 'Unexpected probe process' }
$ruleName='Investify-IPv6-Canary-'+$Token
$receipt='C:\Users\gaura\AInvestifyPrivate\hosting\network\firewall-'+$Token+'.json'
$listener=Get-NetTCPConnection -State Listen -LocalAddress $Address -LocalPort 80 -ErrorAction SilentlyContinue
if ($listener -and $listener.OwningProcess -ne $ProbeProcessId) { throw 'Unrelated process owns this listener' }
if (-not $listener -and ($probe.CommandLine -notmatch '--arm-file' -or $probe.CommandLine -notmatch [regex]::Escape($receipt))) { throw 'Probe must own the listener or wait for this exact grant' }
$created=$false
try {
    if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) { throw 'Probe rule already exists' }
    New-NetFirewallRule -Name $ruleName -DisplayName 'Investify temporary synthetic IPv6 check' `
        -Direction Inbound -Action Allow -Protocol TCP -LocalPort 80 -LocalAddress $Address `
        -InterfaceAlias $networkAddress.InterfaceAlias -Program $probe.ExecutablePath -Profile Any | Out-Null
    $created=$true
    @{ enabled=$true; synthetic_only=$true; address=$Address; port=80; expires_utc=[DateTime]::UtcNow.AddSeconds(110).ToString('o') } |
        ConvertTo-Json | Set-Content -LiteralPath $receipt -Encoding UTF8
    Start-Sleep -Seconds 110
} finally {
    if ($created) {
        Remove-NetFirewallRule -Name $ruleName -ErrorAction Stop
        @{ enabled=$false; removed=$true; synthetic_only=$true; address=$Address; port=80 } |
            ConvertTo-Json | Set-Content -LiteralPath $receipt -Encoding UTF8
    }
}
