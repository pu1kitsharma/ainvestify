#Requires -Version 5.1
<#
Supervise the configured Investify WSL API and loopback Caddy preview.
No model calls, workers, public binds, firewall, router, DNS or release changes.
The enabled WSL systemd unit owns API startup. This process keeps WSL alive.
#>
param([int]$Seconds = 0)
$ErrorActionPreference = 'Stop'
if ($Seconds -lt 0) { throw 'Seconds must be zero or positive' }
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$mutex = New-Object System.Threading.Mutex($false, 'Local\InvestifyLocalHost')
$locked = $false
$wslChild = $null
$caddyChild = $null
try {
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { throw 'Investify local host supervisor is already running' }
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 8080)
    try { $listener.Start() } finally { $listener.Stop() }
    $binary = Join-Path $repoRoot 'deployment/.secrets/caddy/caddy.exe'
    $config = Join-Path $PSScriptRoot 'Caddyfile.preview'
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) { throw 'Verified Caddy binary is missing' }
    $env:INVESTIFY_WEB_ROOT = (Join-Path $repoRoot 'frontend/dist').Replace('\', '/')
    & $binary validate --config $config --adapter caddyfile
    if ($LASTEXITCODE -ne 0) { throw 'Caddy validation failed' }
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)
    $logRoot = Join-Path $repoRoot ('runtime_qualification/local_hosting/' + $stamp + '-linux')
    New-Item -ItemType Directory -Path $logRoot | Out-Null
    $wslChild = Start-Process -FilePath "$env:SystemRoot\System32\wsl.exe" `
        -ArgumentList @('--distribution', 'Investify', '--user', 'investify', '--exec', '/usr/bin/sleep', 'infinity') `
        -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'wsl.stdout.log') `
        -RedirectStandardError (Join-Path $logRoot 'wsl.stderr.log') -PassThru
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    $healthy = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($wslChild.HasExited) { throw 'Investify WSL keepalive exited' }
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
            $healthy = $health.status -eq 'ok'
        } catch { $healthy = $false }
        if ($healthy) { break }
        Start-Sleep -Milliseconds 250
    }
    if (-not $healthy) { throw 'Linux API health deadline expired; inspect the WSL service journal' }
    $caddyChild = Start-Process -FilePath $binary `
        -ArgumentList @('run', '--config', ('"' + $config + '"'), '--adapter', 'caddyfile') `
        -WorkingDirectory $repoRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot 'caddy.stdout.log') `
        -RedirectStandardError (Join-Path $logRoot 'caddy.stderr.log') -PassThru
    @{ supervisor_pid = $PID; wsl_pid = $wslChild.Id; caddy_pid = $caddyChild.Id;
       local_url = 'http://127.0.0.1:8080'; api_backend = 'Investify WSL systemd';
       public_listener = $false; room_worker = $false } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logRoot 'process.json') -Encoding UTF8
    $stopAt = if ($Seconds) { [DateTime]::UtcNow.AddSeconds($Seconds) } else { [DateTime]::MaxValue }
    while ([DateTime]::UtcNow -lt $stopAt) {
        if ($wslChild.HasExited -or $caddyChild.HasExited) { throw 'A local hosting service exited' }
        Start-Sleep -Milliseconds 500
    }
} finally {
    if ($caddyChild -and -not $caddyChild.HasExited) { Stop-Process -Id $caddyChild.Id }
    if ($wslChild -and -not $wslChild.HasExited) { Stop-Process -Id $wslChild.Id }
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
