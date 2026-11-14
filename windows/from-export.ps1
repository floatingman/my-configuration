#Requires -Version 5.1
<#
Turns a `winget export` dump into config.dsc.yaml resource blocks, or reports
how the export differs from what the manifest already declares.

  winget export -o "$env:TEMP\apps.json" --accept-source-agreements

  .\windows\from-export.ps1 "$env:TEMP\apps.json"            # print blocks for installed-but-undeclared apps
  .\windows\from-export.ps1 "$env:TEMP\apps.json" -OutFile blocks.yaml
  .\windows\from-export.ps1 "$env:TEMP\apps.json" -Diff      # three-group report, changes nothing

The export is full of noise (frameworks, runtimes, OEM packages): review the
generated blocks before pasting them into config.dsc.yaml. Do not commit the
raw export file.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExportFile,
    [string]$OutFile,
    [switch]$Diff
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -Path $ExportFile)) {
    Write-Error "Export file not found: $ExportFile"
}

$manifest = Join-Path -Path $PSScriptRoot -ChildPath 'config.dsc.yaml'
if (-not (Test-Path -Path $manifest)) {
    Write-Error "Manifest not found: $manifest"
}

function Slug([string]$Value) {
    ($Value -replace '[^a-zA-Z0-9]+', '-').Trim('-').ToLower()
}

# --- installed packages from the export -----------------------------------
$export = Get-Content -Path $ExportFile -Raw | ConvertFrom-Json
$installed = @{}

if ($export.Sources) {
    foreach ($src in @($export.Sources)) {
        $name = $src.SourceDetails.Name
        foreach ($pkg in @($src.Packages)) {
            if ($pkg -and $pkg.PackageIdentifier) {
                $installed[$pkg.PackageIdentifier] = $name
            }
        }
    }
}
if ($export.Packages) {
    foreach ($pkg in @($export.Packages)) {
        if ($pkg.PackageIdentifier -and -not $installed.ContainsKey($pkg.PackageIdentifier)) {
            $installed[$pkg.PackageIdentifier] = 'winget'
        }
    }
}

# --- declared packages from the manifest ----------------------------------
$text = Get-Content -Path $manifest -Raw
$declared = @{}
$blockPattern = '(?ms)^\s*-\s*resource:\s*Microsoft\.WinGet\.DSC/WinGetPackage\b.*?settings:\s*\n\s*id:\s*([^\s]+)\s*\n\s*source:\s*([^\s#]+)'
foreach ($m in [regex]::Matches($text, $blockPattern)) {
    $declared[$m.Groups[1].Value] = $m.Groups[2].Value
}

$missing = @($declared.Keys | Where-Object { -not $installed.ContainsKey($_) } | Sort-Object)
$undeclared = @($installed.Keys | Where-Object { -not $declared.ContainsKey($_) } | Sort-Object)

if ($Diff) {
    Write-Host "== Declared and installed (manifest is satisfied) =="
    @($declared.Keys | Where-Object { $installed.ContainsKey($_) } | Sort-Object) |
        ForEach-Object { Write-Host "  $_" }
    Write-Host ""
    Write-Host "== Declared but NOT installed (drop from manifest, or install) =="
    foreach ($id in $missing) {
        Write-Host ("  {0}  [source: {1}]" -f $id, $declared[$id])
    }
    Write-Host ""
    Write-Host "== Installed but NOT declared (declare, or leave in the UniGet lane) =="
    foreach ($id in $undeclared) {
        Write-Host ("  {0}  [source: {1}]" -f $id, $installed[$id])
    }
    exit 0
}

if (-not $undeclared) {
    Write-Host "Nothing to add: every installed package is already declared."
    exit 0
}

$blocks = New-Object System.Text.StringBuilder
[void]$blocks.AppendLine('    # ---- from winget export: review before keeping ---------------------')
foreach ($id in $undeclared) {
    $source = $installed[$id]
    if ($source -ne 'winget' -and $source -ne 'msstore') { $source = 'winget' }
    [void]$blocks.AppendLine("    - resource: Microsoft.WinGet.DSC/WinGetPackage")
    [void]$blocks.AppendLine("      id: $(Slug $id)")
    [void]$blocks.AppendLine("      directives:")
    [void]$blocks.AppendLine("        description: Install $id")
    [void]$blocks.AppendLine("      settings:")
    [void]$blocks.AppendLine("        id: $id")
    [void]$blocks.AppendLine("        source: $source")
    [void]$blocks.AppendLine("")
}

$yaml = $blocks.ToString()
if ($OutFile) {
    Set-Content -Path $OutFile -Value $yaml -Encoding utf8
    Write-Host "Wrote $($undeclared.Count) block(s) to $OutFile (review before pasting into config.dsc.yaml)."
}
else {
    Write-Host $yaml
}
