# Windows minimal port

This is a separate, minimal implementation of koe-kichi for Windows.  It does
not import the macOS `voice_typer` package, because the macOS package depends on
MLX, PyObjC, AppKit, and Apple Foundation Models.

## Scope

- Alt hold to record, release to stop
- Alt double tap to start/stop
- `faster-whisper` transcription
- local dictionary replacements and spoken URL expansion
- local punctuation cleanup
- optional OpenAI-compatible postprocess API
- clipboard paste with `Ctrl+V`

The first Windows version is intentionally console-based.  Tray UI, history
viewer, dictionary GUI, and HUD can be added after the core path is verified on
a real Windows machine.

The default configuration is designed for machines without a discrete GPU:

- `whisper_model`: `small`
- `whisper_device`: `cpu`
- `whisper_compute_type`: `int8`
- `postprocess_mode`: `local_punctuation`

That means the app does not require OpenAI, Gemini, Claude, Grok, Ollama, LM
Studio, or any other LLM service.  The speech recognition model is still local
Whisper via `faster-whisper`.  On first use, `faster-whisper` may download the
model unless it is already cached or `whisper_model` points to a local model
directory.

## Double-click installer package

On macOS/Linux, create a source installer zip that can be copied to Windows:

```bash
./scripts/package_windows_source_installer.sh
```

This creates:

```text
dist/KoeKichiWin-source-installer.zip
```

On Windows:

1. Extract the zip.
2. Double-click `Install-KoeKichi.cmd`.
3. Start `Koe Kichi` from the Start Menu.

This path installs Python dependencies into `%LOCALAPPDATA%\KoeKichi\venv`
and runs the app from `%LOCALAPPDATA%\KoeKichi\source-app`.  If Python 3.11 is
missing, the installer tries to install it with `winget`.  The default runtime
uses CPU `small/int8` Whisper and does not require a GPU or external AI API.

## Setup from source

```powershell
cd local-voice-typer
powershell -ExecutionPolicy Bypass -File .\scripts\windows_setup.ps1
```

Manual setup:

```powershell
py -3.11 -m venv .venv-windows
.\.venv-windows\Scripts\python.exe -m pip install -r requirements-windows.txt
.\.venv-windows\Scripts\python.exe -m windows_voice_typer.cli init
```

## Build

Build on Windows, not on macOS:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows_build.ps1
```

This creates:

```text
dist\KoeKichiWin\KoeKichiWin.exe
```

`--onedir` is the default because it starts faster and is easier to debug than a
single-file executable.

## Install

Install the built app for the current Windows user:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows_install.ps1
```

This copies the app to:

```text
%LOCALAPPDATA%\KoeKichi\app
```

and creates Start Menu shortcuts for:

- `Koe Kichi`
- `Koe Kichi Diagnose`
- `Uninstall Koe Kichi`

To start at login:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows_install.ps1 -LaunchAtLogin
```

Uninstall while keeping user config and dictionary:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\KoeKichi\windows_uninstall.ps1"
```

Clean uninstall including config and dictionary:

```powershell
powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\KoeKichi\windows_uninstall.ps1" -RemoveUserData
```

## Installer package

Create a portable installer zip or Inno Setup `.exe` on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows_make_installer.ps1
```

If Inno Setup 6 is installed, the same command also builds:

```text
dist\KoeKichiWinSetup.exe
```

Otherwise it builds:

```text
dist\KoeKichiWin-portable-installer.zip
```

The portable zip contains the built app plus `Install-KoeKichi.cmd`,
`windows_install.ps1`, and `windows_uninstall.ps1`.

For a one-click `.exe` installer, install Inno Setup 6 on the Windows build
machine and run:

```cmd
Build-KoeKichiWinSetup.cmd
```

## Run

```powershell
.\.venv-windows\Scripts\python.exe -m windows_voice_typer.cli diagnose
.\.venv-windows\Scripts\python.exe -m windows_voice_typer.cli run
```

Config and dictionary are stored under:

```text
%APPDATA%\KoeKichi\config.json
%APPDATA%\KoeKichi\dictionary.json
```

## AI postprocess choice

Windows has no Apple Foundation Models path, so the stable minimal choices are:

- `off`: no postprocess
- `local_punctuation`: local regex punctuation cleanup
- `openai_compatible_punctuation`: call `/v1/chat/completions`
- `openai_compatible_rewrite`: call `/v1/chat/completions`

The OpenAI-compatible path is deliberately provider-neutral.  It can point at:

- OpenAI-compatible hosted APIs
- Ollama local server (`http://localhost:11434/v1`)
- LM Studio local server (`http://localhost:1234/v1`)
- any provider or proxy that exposes `/v1/chat/completions`

Example config for Ollama:

```json
{
  "postprocess_mode": "openai_compatible_punctuation",
  "openai_compatible_base_url": "http://localhost:11434/v1",
  "openai_compatible_model": "qwen3:4b",
  "openai_compatible_api_key_env": "OLLAMA_API_KEY"
}
```

For localhost endpoints the API key may be empty.

## Packaging direction

The maintained packaging path is now:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\windows_build.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\windows_make_installer.ps1
```

The generated installer should still be smoke-tested on the target Windows
version, especially keyboard capture, microphone selection, and paste behavior.
