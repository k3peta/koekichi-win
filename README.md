# koe-kichi-win

Koe Kichi is a small Windows voice input app for Japanese dictation. It runs
from the task tray, records with a configurable hotkey, transcribes locally with
faster-whisper by default, and pastes the result into the current text field.

## Highlights

- Default input: Alt double-tap to start recording, Alt double-tap again to
  stop, transcribe, and paste.
- Safe input backend: polling by default, so keyboard and mouse hooks do not
  lock up the machine.
- Local-first transcription: faster-whisper on CPU by default.
- Optional Gemini API transcription: one stopped recording is sent as a single
  audio request when selected.
- Popup HUD: appears near the cursor while recording/processing and auto-hides
  after paste.
- Task tray menu: settings, dictionary registration, history, and exit.
- Dictionary: register spoken forms such as `春シネーション` to
  `ハルシネーション`.
- Whisper model selection: `small`, `medium`, `large-v3`, and `turbo`.

## Install

1. Download and unzip the Windows source package.
2. Double-click `Install-KoeKichi.cmd`.
3. Choose microphone, activation key, Whisper model, transcription backend, and
   login startup behavior during initial setup.
4. Start Koe Kichi from the Start Menu.

The installer creates a Python 3.11 virtual environment under
`%LOCALAPPDATA%\KoeKichi`. If Python 3.11 is not available, it tries to install
Python through winget.

## Settings

Open settings from the task tray icon or Start Menu. You can change:

- microphone
- activation key
- hold-to-record key
- middle-click recording
- transcription backend
- Whisper model
- Gemini API key environment variable
- launch-at-login

Gemini API keys are saved to the user environment variable you choose. API keys
are not stored in this repository, dictionary, history, or release package.

## Model Notes

`small` remains the default because it is the most practical CPU balance for
ordinary Windows machines. `turbo` is based on `large-v3` and can be a strong
speed/accuracy choice on GPU-equipped machines, but it is still much larger than
`small`; CPU-only machines may not benefit enough to make it the default.

## Uninstall

Run `Uninstall-KoeKichi.cmd` from the package or `Uninstall Koe Kichi` from the
Start Menu.

## License

Koe Kichi is released under the MIT License. See `LICENSE` and
`THIRD_PARTY_NOTICES.md`.
