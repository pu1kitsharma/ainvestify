#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
Install the pinned Microsoft WSL runtime and enable Virtual Machine Platform.
No distribution, model, application migration, public listener or reboot.
#>
param(
    [string]$Installer = (Join-Path $PSScriptRoot '../.secrets/wsl/wsl.3.0.3.0.x64.msi'),
    [string]$LogRoot = 'C:\Users\gaura\AInvestifyPrivate\hosting\wsl'
)

$ErrorActionPreference = 'Stop'
$expectedHash = 'ae977286974255bd26bf925f00f40f5692c6b2084155cbc0563c09aea091f211'
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
if ((Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'WSL installer digest differs from the pinned official release.'
}
$signature = Get-AuthenticodeSignature -LiteralPath $installerPath
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'WSL installer must carry a valid Microsoft signature.'
}
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
$receipt = Join-Path $LogRoot 'installation.json'
if (Test-Path -LiteralPath $receipt) { throw 'Installation receipt exists; inspect before rerunning.' }

try {
    $msiLog = Join-Path $LogRoot 'msi.log'
    $arguments = @('/i', ('"' + $installerPath + '"'), '/qn', '/norestart', 'REBOOT=ReallySuppress',
                   '/L*v', ('"' + $msiLog + '"'))
    $installation = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" `
        -ArgumentList $arguments -WindowStyle Hidden -PassThru -Wait
    if ($installation.ExitCode -notin @(0, 3010)) {
        throw ('WSL installer failed with exit code ' + $installation.ExitCode)
    }
    $feature = Get-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform
    $restartNeeded = $installation.ExitCode -eq 3010
    if ($feature.State -ne 'Enabled') {
        $enabled = Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
        $restartNeeded = $restartNeeded -or $enabled.RestartNeeded
    }
    @{
        contract = 'local-wsl-foundation-v1'
        runtime_version = '3.0.3'
        installer_sha256 = $expectedHash
        installed = $true
        reboot_required = [bool]$restartNeeded
        reboot_initiated = $false
        distribution_installed_by_this_script = $false
        private_worker_qualified = $false
        completed_utc = [DateTime]::UtcNow.ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $receipt -Encoding UTF8
} catch {
    @{ installed = $false; error = $_.Exception.Message; reboot_initiated = $false } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LogRoot 'failed-installation.json') -Encoding UTF8
    throw
}
