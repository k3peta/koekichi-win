[CmdletBinding()]
param(
    [switch]$OneFile,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Block
    )
    Write-Host "==> $Name"
    & $Block
}

Invoke-Step "check Python 3.11" {
    py -3.11 -c "import sys; print(sys.executable); print(sys.version)"
}

$Venv = Join-Path $Root ".venv-windows"
$Python = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Invoke-Step "create .venv-windows" {
        py -3.11 -m venv $Venv
    }
}

Invoke-Step "install Windows runtime dependencies" {
    & $Python -m pip install --upgrade pip wheel setuptools
    & $Python -m pip install -r (Join-Path $Root "requirements-windows.txt") pyinstaller
}

if (-not $SkipTests) {
    Invoke-Step "run Windows port tests" {
        & $Python -m unittest tests.test_windows_port
    }
}

$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--console",
    "--name", "KoeKichiWin",
    "--collect-all", "faster_whisper",
    "--collect-all", "ctranslate2",
    "--collect-all", "tokenizers",
    "--collect-all", "huggingface_hub",
    "--collect-all", "sounddevice"
)

$IconPath = Join-Path $Root "assets\koe-kichi.ico"
if (Test-Path $IconPath) {
    $PyInstallerArgs += @("--icon", $IconPath)
}

if ($OneFile) {
    $PyInstallerArgs += "--onefile"
} else {
    $PyInstallerArgs += "--onedir"
}

$PyInstallerArgs += (Join-Path $Root "koe_kichi_win.py")

Invoke-Step "build KoeKichiWin with PyInstaller" {
    & $Python -m PyInstaller @PyInstallerArgs
}

$Exe = if ($OneFile) {
    Join-Path $Root "dist\KoeKichiWin.exe"
} else {
    Join-Path $Root "dist\KoeKichiWin\KoeKichiWin.exe"
}

if (-not (Test-Path $Exe)) {
    throw "Build finished but executable was not found: $Exe"
}

Write-Host "Built: $Exe"
