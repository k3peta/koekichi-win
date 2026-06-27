[CmdletBinding()]
param(
    [switch]$RemoveUserData
)

$ErrorActionPreference = "Stop"

$InstallRoot = Join-Path $env:LOCALAPPDATA "KoeKichi"
$UserDataRoot = Join-Path $env:APPDATA "KoeKichi"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Koe Kichi"
$StartupShortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\Koe Kichi.lnk"

$processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    ($_.Name -like "python*" -and $_.CommandLine -like "*windows_voice_typer*") -or
    ($_.Name -like "KoeKichiWin*")
})
foreach ($process in $processes) {
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    } catch {
    }
}

if (Test-Path $StartupShortcut) {
    Remove-Item $StartupShortcut -Force
}
if (Test-Path $StartMenuDir) {
    Remove-Item $StartMenuDir -Recurse -Force
}
if (Test-Path $InstallRoot) {
    Remove-Item $InstallRoot -Recurse -Force
}
if ($RemoveUserData -and (Test-Path $UserDataRoot)) {
    Remove-Item $UserDataRoot -Recurse -Force
}

Write-Host "Koe Kichi application files were removed."
if ($RemoveUserData) {
    Write-Host "User config and dictionary were removed."
} else {
    Write-Host "User config and dictionary were kept at: $UserDataRoot"
}
