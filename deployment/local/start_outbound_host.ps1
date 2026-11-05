#Requires -Version 5.1
<#
Supervise a named outbound tunnel and a host-pinned proxy; default to sign-in-only.
Explicit private-workflows mode routes authenticated workspace APIs. It does not
start room workers or grant final investor release, which requires exact-file checks.
The tunnel token stays outside Git and is passed by file, never command line.
#>
param([int]$Seconds = 0,
      [ValidateSet('sign-in-acceptance','private-workflows')][string]$Mode = 'sign-in-acceptance')
$ErrorActionPreference = 'Stop'
if ($Seconds -lt 0) { throw 'Seconds must be zero or positive' }
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$privateRoot = Join-Path $env:USERPROFILE 'AInvestifyPrivate/hosting/cloudflared'
$cloudBinary = Join-Path $privateRoot 'cloudflared.exe'
$tokenFile = Join-Path $privateRoot 'tunnel.token'
$caddyBinary = Join-Path $repoRoot 'deployment/.secrets/caddy/caddy.exe'
$config = Join-Path $PSScriptRoot $(if ($Mode -eq 'private-workflows') {'Caddyfile.tunnel'} else {'Caddyfile.tunnel-acceptance'})
$mutex = New-Object System.Threading.Mutex($false, 'Local\InvestifyOutboundHost')
$locked = $false
$caddyChild = $null
$tunnelChild = $null
$wslChild = $null
try {
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { throw 'Investify outbound host is already running' }
    foreach ($path in @($cloudBinary, $tokenFile, $caddyBinary)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'A verified binary or private tunnel credential file is missing' }
    }
    $actual = (Get-FileHash -LiteralPath $cloudBinary -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne '411b16d40c8d872243efeb52c550053d00af0a8a97fbb32e730fb8aba429eaa8') {
        throw 'cloudflared differs from the verified 2026.10.4 release'
    }
    if ((Get-AuthenticodeSignature -LiteralPath $cloudBinary).Status -ne 'Valid') {
        throw 'cloudflared Authenticode verification failed'
    }
    foreach ($port in @(8081, 18082)) {
        $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $port)
        try { $listener.Start() } finally { $listener.Stop() }
    }
    $env:INVESTIFY_WEB_ROOT = (Join-Path $repoRoot 'frontend/dist').Replace('\', '/')
    & $caddyBinary validate --config $config --adapter caddyfile
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance proxy configuration is invalid' }
    # systemd alone does not keep a WSL distribution running. Own this handle
    # independently of the separate loopback preview supervisor.
    $wslChild = Start-Process -FilePath "$env:SystemRoot\System32\wsl.exe" `
        -ArgumentList @('--distribution', 'Investify', '--user', 'investify', '--exec', '/usr/bin/sleep', 'infinity') `
        -WindowStyle Hidden -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(90)
    $healthy = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($wslChild.HasExited) { throw 'Investify WSL keepalive exited' }
        try {
            $auth = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/auth/config' -TimeoutSec 2
            $healthy = $auth.configured -eq $true -and $auth.local_password_enabled -eq $false
        } catch { $healthy = $false }
        if ($healthy) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $healthy) { throw 'Configured OIDC API did not become ready' }
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
    $logRoot = Join-Path $repoRoot ('runtime_qualification/outbound_host/' + $stamp)
    New-Item -ItemType Directory -Path $logRoot | Out-Null
    $caddyChild = Start-Process -FilePath $caddyBinary `
        -ArgumentList @('run', '--config', ('"' + $config + '"'), '--adapter', 'caddyfile') `
        -WorkingDirectory $repoRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot 'caddy.stdout.log') `
        -RedirectStandardError (Join-Path $logRoot 'caddy.stderr.log') -PassThru
    Start-Sleep -Milliseconds 500
    if ($caddyChild.HasExited) { throw 'Acceptance proxy exited' }
    $env:TUNNEL_TOKEN = $null
    $tunnelChild = Start-Process -FilePath $cloudBinary `
        -ArgumentList @('tunnel', '--no-autoupdate', '--protocol', 'http2',
                        '--metrics', '127.0.0.1:18082', 'run', '--token-file', ('"' + $tokenFile + '"')) `
        -WorkingDirectory $privateRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot 'tunnel.stdout.log') `
        -RedirectStandardError (Join-Path $logRoot 'tunnel.stderr.log') -PassThru
    @{ supervisor_pid = $PID; caddy_pid = $caddyChild.Id; tunnel_pid = $tunnelChild.Id; wsl_pid = $wslChild.Id;
       origin = 'http://127.0.0.1:8081'; hostname = 'investify.fyi';
       private_workspace_routes = ($Mode -eq 'private-workflows'); mode = $Mode;
       token_in_command_line = $false } | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $logRoot 'process.json') -Encoding UTF8
    $stopAt = if ($Seconds) { [DateTime]::UtcNow.AddSeconds($Seconds) } else { [DateTime]::MaxValue }
    $nextHealth = [DateTime]::UtcNow
    $healthFailures = 0
    while ([DateTime]::UtcNow -lt $stopAt) {
        if ($caddyChild.HasExited -or $tunnelChild.HasExited -or $wslChild.HasExited) { throw 'Outbound hosting child exited' }
        if ([DateTime]::UtcNow -ge $nextHealth) {
            try {
                $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
                if ($health.status -ne 'ok') { throw 'API is unhealthy' }
                $healthFailures = 0
            } catch { $healthFailures++ }
            if ($healthFailures -ge 3) { throw 'API health failed three consecutive checks' }
            $nextHealth = [DateTime]::UtcNow.AddSeconds(10)
        }
        Start-Sleep -Milliseconds 500
    }
} finally {
    if ($tunnelChild -and -not $tunnelChild.HasExited) { Stop-Process -Id $tunnelChild.Id }
    if ($caddyChild -and -not $caddyChild.HasExited) { Stop-Process -Id $caddyChild.Id }
    if ($wslChild -and -not $wslChild.HasExited) { Stop-Process -Id $wslChild.Id }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
