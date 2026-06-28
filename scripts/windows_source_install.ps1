[CmdletBinding()]
param(
    [switch]$LaunchAtLogin,
    [switch]$NoPythonBootstrap,
    [switch]$NoShortcuts,
    [switch]$SkipModelDownload
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$InstallRoot = Join-Path $env:LOCALAPPDATA "KoeKichi"
$AppDir = Join-Path $InstallRoot "source-app"
$VenvDir = Join-Path $InstallRoot "venv"
$StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Koe Kichi"
$StartupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Block
    )
    Write-Host "==> $Name"
    & $Block
}

function Stop-ExistingKoeKichi {
    $processes = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        ($_.Name -like "python*" -and $_.CommandLine -like "*windows_voice_typer*") -or
        ($_.Name -like "KoeKichiWin*")
    })
    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            Write-Host "Stopped existing Koe Kichi process: $($process.ProcessId)"
        } catch {
            Write-Host "Could not stop process $($process.ProcessId): $($_.Exception.Message)"
        }
    }
}

function Get-Python311Command {
    $ProgramFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        try {
            & py -3.11 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" | Out-Null
            return @("py", "-3.11")
        } catch {
        }
    }

    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($Python) {
        try {
            & python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" | Out-Null
            return @("python")
        } catch {
        }
    }
    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe")
    )
    if ($ProgramFilesX86) {
        $Candidates += (Join-Path $ProgramFilesX86 "Python311\python.exe")
    }
    foreach ($Candidate in $Candidates) {
        if (-not $Candidate -or -not (Test-Path $Candidate)) {
            continue
        }
        try {
            & $Candidate -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)" | Out-Null
            return @($Candidate)
        } catch {
        }
    }
    return $null
}

function Install-Python311 {
    if ($NoPythonBootstrap) {
        throw "Python 3.11 was not found. Install Python 3.11 and run Install-KoeKichi.cmd again."
    }
    $Winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $Winget) {
        throw "Python 3.11 was not found, and winget is unavailable. Install Python 3.11 and run Install-KoeKichi.cmd again."
    }
    Write-Host "Python 3.11 was not found. Installing Python 3.11 with winget..."
    & winget install --id Python.Python.3.11 -e --source winget --silent --accept-source-agreements --accept-package-agreements
}

function New-Shortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$Description,
        [string]$Icon = ""
    )
    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($Path)
    $Shortcut.TargetPath = $Target
    $Shortcut.Arguments = $Arguments
    $Shortcut.WorkingDirectory = $WorkingDirectory
    $Shortcut.Description = $Description
    if ($Icon -and (Test-Path $Icon)) {
        $Shortcut.IconLocation = $Icon
    } else {
        $Shortcut.IconLocation = $Target
    }
    $Shortcut.Save()
}

function Copy-AppSources {
    if (Test-Path $AppDir) {
        Remove-Item $AppDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
    Copy-Item (Join-Path $Root "windows_voice_typer") $AppDir -Recurse -Force
    Copy-Item (Join-Path $Root "koe_kichi_win.py") $AppDir -Force
    Copy-Item (Join-Path $Root "requirements-windows.txt") $AppDir -Force
    if (Test-Path (Join-Path $Root "assets\koe-kichi.ico")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "assets") | Out-Null
        Copy-Item (Join-Path $Root "assets\koe-kichi.ico") (Join-Path $AppDir "assets") -Force
    }
    if (Test-Path (Join-Path $Root "docs\windows_port.md")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $AppDir "docs") | Out-Null
        Copy-Item (Join-Path $Root "docs\windows_port.md") (Join-Path $AppDir "docs") -Force
    }
}

function Invoke-PythonCommand {
    param(
        [string[]]$Command,
        [string[]]$Arguments
    )
    $Exe = $Command[0]
    $BaseArgs = @()
    if ($Command.Count -gt 1) {
        $BaseArgs = $Command[1..($Command.Count - 1)]
    }
    & $Exe @BaseArgs @Arguments
}

$PythonCommand = Get-Python311Command
if (-not $PythonCommand) {
    Install-Python311
    $PythonCommand = Get-Python311Command
}
if (-not $PythonCommand) {
    throw "Python 3.11 is still unavailable after bootstrap."
}

Invoke-Step "stop existing Koe Kichi" {
    Stop-ExistingKoeKichi
}

Invoke-Step "copy application files" {
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
    Copy-AppSources
    Copy-Item (Join-Path $Root "scripts\windows_uninstall.ps1") (Join-Path $InstallRoot "windows_uninstall.ps1") -Force
}

Invoke-Step "create Python virtual environment" {
    if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
        Invoke-PythonCommand -Command $PythonCommand -Arguments @("-m", "venv", $VenvDir)
    }
}

$Python = Join-Path $VenvDir "Scripts\python.exe"
$Pythonw = Join-Path $VenvDir "Scripts\pythonw.exe"
if (-not (Test-Path $Pythonw)) {
    $Pythonw = $Python
}
$Icon = Join-Path $AppDir "assets\koe-kichi.ico"

Invoke-Step "install dependencies" {
    & $Python -m pip install --upgrade pip wheel setuptools
    & $Python -m pip install -r (Join-Path $AppDir "requirements-windows.txt")
}

Invoke-Step "initialize config and dictionary" {
    Push-Location $AppDir
    try {
        & $Python -m windows_voice_typer.cli init
    } finally {
        Pop-Location
    }
}

Invoke-Step "choose microphone, activation key, Whisper model, transcription backend, and login startup" {
    Push-Location $AppDir
    try {
        & $Python -m windows_voice_typer.cli configure
    } finally {
        Pop-Location
    }
}

if (-not $SkipModelDownload) {
    Invoke-Step "download and verify Whisper model" {
        Push-Location $AppDir
        try {
            & $Python -m windows_voice_typer.cli setup --model-timeout-seconds 900
            if ($LASTEXITCODE -ne 0) {
                throw "Koe Kichi setup check failed with exit code $LASTEXITCODE."
            }
        } finally {
            Pop-Location
        }
    }
}

if (-not $NoShortcuts) {
    Invoke-Step "create Start Menu shortcuts" {
        New-Item -ItemType Directory -Force -Path $StartMenuDir | Out-Null
        New-Shortcut `
            -Path (Join-Path $StartMenuDir "Koe Kichi.lnk") `
            -Target $Pythonw `
            -Arguments "-m windows_voice_typer.cli run" `
            -WorkingDirectory $AppDir `
            -Description "Run Koe Kichi voice input" `
            -Icon $Icon
        New-Shortcut `
            -Path (Join-Path $StartMenuDir "Koe Kichi Setup Check.lnk") `
            -Target $Python `
            -Arguments "-m windows_voice_typer.cli setup --model-timeout-seconds 900" `
            -WorkingDirectory $AppDir `
            -Description "Download/check Koe Kichi model and audio setup" `
            -Icon $Icon
        New-Shortcut `
            -Path (Join-Path $StartMenuDir "Koe Kichi Settings.lnk") `
            -Target $Python `
            -Arguments "-m windows_voice_typer.cli configure" `
            -WorkingDirectory $AppDir `
            -Description "Choose Koe Kichi microphone, activation key, Whisper model, transcription backend, and login startup" `
            -Icon $Icon
        New-Shortcut `
            -Path (Join-Path $StartMenuDir "Koe Kichi Diagnose.lnk") `
            -Target $Python `
            -Arguments "-m windows_voice_typer.cli diagnose --check-model" `
            -WorkingDirectory $AppDir `
            -Description "Show Koe Kichi diagnostics" `
            -Icon $Icon
        New-Shortcut `
            -Path (Join-Path $StartMenuDir "Uninstall Koe Kichi.lnk") `
            -Target "powershell.exe" `
            -Arguments "-ExecutionPolicy Bypass -File `"$InstallRoot\windows_uninstall.ps1`"" `
            -WorkingDirectory $InstallRoot `
            -Description "Uninstall Koe Kichi"
    }
}

if ($LaunchAtLogin) {
    Invoke-Step "create startup shortcut" {
        New-Shortcut `
            -Path (Join-Path $StartupDir "Koe Kichi.lnk") `
            -Target $Pythonw `
            -Arguments "-m windows_voice_typer.cli run" `
            -WorkingDirectory $AppDir `
            -Description "Run Koe Kichi at login" `
            -Icon $Icon
    }
}

Write-Host ""
Write-Host "Installed Koe Kichi to: $AppDir"
Write-Host "Config and dictionary: $env:APPDATA\KoeKichi"
Write-Host "Default mode: Alt double-tap, local Whisper on CPU, popup HUD near the active text field."
Write-Host "Start it from the Start Menu: Koe Kichi"
