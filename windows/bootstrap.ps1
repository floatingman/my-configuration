#Requires -Version 5.1
<#
Windows entrypoint of this repo (the Ansible side is Linux-only).

  Apply :  .\windows\bootstrap.ps1          install/repair desired state
  Drift :  .\windows\bootstrap.ps1 -Test    report compliance, change nothing

Idempotent: WinGet Configuration is desired-state, so re-running after
everything is installed reports all resources compliant and changes nothing.

Run from an elevated terminal when a package needs a machine-scope install;
user-scope packages work from a normal terminal.
#>
[CmdletBinding()]
param(
    [switch]$Test
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Error @'
winget not found. Install "App Installer" from the Microsoft Store:
open ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1
then open a new terminal and re-run this script.
'@
}

$config = Join-Path -Path $PSScriptRoot -ChildPath 'config.dsc.yaml'
if (-not (Test-Path -Path $config)) {
    Write-Error "Configuration file not found: $config"
}

if ($Test) {
    & winget configure test --file $config
}
else {
    & winget configure --file $config --accept-configuration-agreements --disable-interactivity
}

exit $LASTEXITCODE
