[CmdletBinding()]
param(
    [switch]$LaunchAtLogin,
    [switch]$SkipBuild,
    [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = if ((Split-Path -Leaf $ScriptDir) -eq "scripts") {
    Split-Path -Parent $ScriptDir
} else {
    $ScriptDir
}
$InstallRoot = Join-Path $env:LOCALAPPDATA "KoeKichi"
$AppDir = Join-Path $InstallRoot "app"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Koe Kichi"
$StartupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$OneFileExe = Join-Path $Root "dist\KoeKichiWin.exe"
$UninstallSource = if (Test-Path (Join-Path $Root "scripts\windows_uninstall.ps1")) {
    Join-Path $Root "scripts\windows_uninstall.ps1"
} else {
    Join-Path $Root "windows_uninstall.ps1"
}

function New-Shortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$Description
    )
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($Path)
    $Shortcut.TargetPath = $Target
    $Shortcut.Arguments = $Arguments
    $Shortcut.WorkingDirectory = $WorkingDirectory
    $Shortcut.Description = $Description
    $Shortcut.IconLocation = $Target
    $Shortcut.Save()
}

function Get-BuiltDir {
    if (Test-Path (Join-Path $Root "dist\KoeKichiWin\KoeKichiWin.exe")) {
        return (Join-Path $Root "dist\KoeKichiWin")
    }
    if (Test-Path (Join-Path $Root "KoeKichiWin\KoeKichiWin.exe")) {
        return (Join-Path $Root "KoeKichiWin")
    }
    return (Join-Path $Root "dist\KoeKichiWin")
}

$BuiltDir = Get-BuiltDir
$BuiltExe = Join-Path $BuiltDir "KoeKichiWin.exe"

if (-not $SkipBuild -and -not (Test-Path $BuiltExe) -and -not (Test-Path $OneFileExe)) {
    & (Join-Path $Root "scripts\windows_build.ps1")
    $BuiltDir = Get-BuiltDir
    $BuiltExe = Join-Path $BuiltDir "KoeKichiWin.exe"
}

New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

if (Test-Path $BuiltExe) {
    if (Test-Path $AppDir) {
        Remove-Item $AppDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    Copy-Item (Join-Path $BuiltDir "*") $AppDir -Recurse -Force
    $Exe = Join-Path $AppDir "KoeKichiWin.exe"
} elseif (Test-Path $OneFileExe) {
    Copy-Item $OneFileExe (Join-Path $AppDir "KoeKichiWin.exe") -Force
    $Exe = Join-Path $AppDir "KoeKichiWin.exe"
} else {
    throw "No Windows build found. Run scripts\windows_build.ps1 first."
}

Copy-Item $UninstallSource (Join-Path $InstallRoot "windows_uninstall.ps1") -Force

& $Exe init

if (-not $NoShortcuts) {
    New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
    New-Shortcut `
        -Path (Join-Path $StartMenuDir "Koe Kichi.lnk") `
        -Target $Exe `
        -Arguments "run" `
        -WorkingDirectory $AppDir `
        -Description "Run Koe Kichi voice input"
    New-Shortcut `
        -Path (Join-Path $StartMenuDir "Koe Kichi Diagnose.lnk") `
        -Target $Exe `
        -Arguments "diagnose" `
        -WorkingDirectory $AppDir `
        -Description "Show Koe Kichi diagnostics"
    New-Shortcut `
        -Path (Join-Path $StartMenuDir "Uninstall Koe Kichi.lnk") `
        -Target "powershell.exe" `
        -Arguments "-ExecutionPolicy Bypass -File `"$InstallRoot\windows_uninstall.ps1`"" `
        -WorkingDirectory $InstallRoot `
        -Description "Uninstall Koe Kichi"
}

if ($LaunchAtLogin) {
    New-Shortcut `
        -Path (Join-Path $StartupDir "Koe Kichi.lnk") `
        -Target $Exe `
        -Arguments "run" `
        -WorkingDirectory $AppDir `
        -Description "Run Koe Kichi at login"
}

Write-Host "Installed Koe Kichi to: $AppDir"
Write-Host "Config and dictionary: $env:APPDATA\KoeKichi"
