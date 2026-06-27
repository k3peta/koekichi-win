[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$Dist = Join-Path $Root "dist"
$BuiltDir = Join-Path $Dist "KoeKichiWin"
$ReleaseDir = Join-Path $Dist "windows-release"
$ZipPath = Join-Path $Dist "KoeKichiWin-portable-installer.zip"

if (-not $SkipBuild) {
    & (Join-Path $Root "scripts\windows_build.ps1")
}

if (-not (Test-Path (Join-Path $BuiltDir "KoeKichiWin.exe"))) {
    throw "Expected build output is missing: $BuiltDir"
}

if (Test-Path $ReleaseDir) {
    Remove-Item $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

Copy-Item $BuiltDir (Join-Path $ReleaseDir "KoeKichiWin") -Recurse -Force
Copy-Item (Join-Path $Root "scripts\windows_install.ps1") $ReleaseDir -Force
Copy-Item (Join-Path $Root "scripts\windows_uninstall.ps1") $ReleaseDir -Force
Copy-Item (Join-Path $Root "docs\windows_port.md") $ReleaseDir -Force
if (Test-Path (Join-Path $Root "Install-KoeKichi.cmd")) {
    Copy-Item (Join-Path $Root "Install-KoeKichi.cmd") $ReleaseDir -Force
}
if (Test-Path (Join-Path $Root "installers\windows\README-はじめにお読みください.txt")) {
    Copy-Item (Join-Path $Root "installers\windows\README-はじめにお読みください.txt") (Join-Path $ReleaseDir "README-Windows.txt") -Force
}

if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}
Compress-Archive -Path (Join-Path $ReleaseDir "*") -DestinationPath $ZipPath

$InnoCandidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if ($InnoCandidates.Count -gt 0) {
    $Iscc = $InnoCandidates[0]
    $Iss = Join-Path $Root "installers\windows\KoeKichiWin.iss"
    $IsccArgs = @("/DSourceDir=$BuiltDir", "/DOutputDir=$Dist")
    $IconFile = Join-Path $Root "assets\koe-kichi.ico"
    if (Test-Path $IconFile) {
        $IsccArgs += "/DIconFile=$IconFile"
    }
    $IsccArgs += $Iss
    & $Iscc @IsccArgs
    Write-Host "Built Inno Setup installer in: $Dist"
} else {
    Write-Host "Inno Setup was not found. Portable installer zip was built instead."
}

Write-Host "Portable installer zip: $ZipPath"
