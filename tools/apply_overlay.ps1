param(
    [Parameter(Mandatory = $true)]
    [string]$X265Root,
    [switch]$NoBackup
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$overlayRoot = Join-Path $repoRoot 'x265_overlay'
$targetRoot = (Resolve-Path -LiteralPath $X265Root).Path

if (-not (Test-Path -LiteralPath (Join-Path $targetRoot 'source\x265.h'))) {
    throw "Target does not look like an x265 source tree: $targetRoot"
}

$files = Get-ChildItem -LiteralPath $overlayRoot -Recurse -File
if ($files.Count -eq 0) {
    throw "No overlay files found: $overlayRoot"
}

$backupRoot = $null
if (-not $NoBackup) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupRoot = Join-Path $targetRoot ('.hw-hme-backup-' + $stamp)
}

foreach ($file in $files) {
    $relative = $file.FullName.Substring($overlayRoot.Length).TrimStart('\', '/')
    $destination = Join-Path $targetRoot $relative
    $destinationDir = Split-Path -Parent $destination
    New-Item -ItemType Directory -Force -Path $destinationDir | Out-Null

    if ($backupRoot -and (Test-Path -LiteralPath $destination)) {
        $backup = Join-Path $backupRoot $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backup) | Out-Null
        Copy-Item -LiteralPath $destination -Destination $backup -Force
    }

    Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
    Write-Host "Applied $relative"
}

if ($backupRoot) {
    Write-Host "Backup: $backupRoot"
}
Write-Host "Overlay applied to: $targetRoot"
