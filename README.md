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
- Model setup from the task tray when the Whisper model is not downloaded yet.
- Dictionary: register spoken forms such as `春シネーション` to
  `ハルシネーション`.
- Whisper model selection: `small`, `medium`, `large-v3`, and `turbo`.
- Whisper accuracy selection: beam size `1`, `3`, or `5`.
- Whisper hints: safe auto prompt hints are on by default, while stronger
  `hotwords` stay off unless you enable them.
- Optional AI text correction through an OpenAI-compatible endpoint such as
  OpenAI API or local Ollama.

## Install

1. Download and unzip the Windows source package.
2. Double-click `Install-KoeKichi.cmd`.
3. Choose microphone, activation key, Whisper model/accuracy, transcription
   backend, text correction mode, and login startup behavior during initial
   setup.
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
- Whisper accuracy
- text correction mode
- OpenAI-compatible AI correction endpoint/model/key environment variable
- Gemini API key environment variable
- launch-at-login

Gemini and AI correction API keys are saved to the user environment variable
you choose. API keys are not stored in this repository, dictionary, history, or
release package.

## Model Notes

`small` remains the default because it is the most practical CPU balance for
ordinary Windows machines. `turbo` is based on `large-v3` and can be a strong
speed/accuracy choice on GPU-equipped machines, but it is still much larger than
`small`; CPU-only machines may not benefit enough to make it the default.

Beam size controls the speed/accuracy tradeoff for local Whisper. `1` is the
fastest, `3` is the balanced default, and `5` can reduce recognition mistakes at
the cost of more CPU time. Koe Kichi disables Whisper previous-text conditioning
by default to reduce repeated phrases and transcript hallucinations.

Whisper hinting is intentionally conservative. Koe Kichi pulls short canonical
terms from dictionary replacement targets plus URL titles, feeds them into
`initial_prompt` as a light hint, and keeps `hotwords` off by default because
they are much more forceful. The automatic hint list is short, deduplicated,
and capped so it does not turn into a giant pronunciation dump.

The default text correction mode is local fixed correction, which is fast and
private. AI correction is optional and should be treated as a light cleanup pass:
it is prompted to fix recognition mistakes, repetition, and punctuation without
adding meaning.

If the selected Whisper model is not downloaded yet, choose
`モデルセットアップ...` from the task tray menu. Koe Kichi also starts model
setup automatically when local transcription fails with a model-readiness error.

## Uninstall

Run `Uninstall-KoeKichi.cmd` from the package or `Uninstall Koe Kichi` from the
Start Menu.

## License

Koe Kichi is released under the MIT License. See `LICENSE` and
`THIRD_PARTY_NOTICES.md`.
