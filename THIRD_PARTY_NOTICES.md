# Third-Party Notices

Koe Kichi is released under the MIT License. It also uses third-party
components with their own licenses. Keep the relevant license files and package
metadata when redistributing source archives or bundled Windows builds.

## Runtime Dependencies

| Component | Purpose | License |
| --- | --- | --- |
| faster-whisper | Local Whisper transcription | MIT |
| CTranslate2 | Whisper inference runtime | MIT |
| ONNX Runtime | Runtime dependency used by faster-whisper stack | MIT |
| PyAV | Audio/media handling | BSD-3-Clause |
| NumPy | Numeric processing | BSD-3-Clause and related permissive terms |
| sounddevice | Microphone capture | MIT |
| pynput | Optional legacy input hooks | LGPLv3 |
| pyperclip | Clipboard support | BSD |
| pystray | Task tray icon | LGPLv3 |
| Pillow | Tray icon image support | MIT-CMU |
| huggingface_hub | Model download/cache support | Apache-2.0 |
| tokenizers | Whisper tokenizer support | Apache-2.0 |
| tqdm | Progress utility used by dependencies | MPL-2.0 and MIT |
| httpx | HTTP client used by dependencies | BSD-3-Clause |
| protobuf | Serialization runtime used by dependencies | BSD-3-Clause |
| PyYAML | YAML support used by dependencies | MIT |

## Build Tooling

Standalone EXE builds use PyInstaller when `work/build_koekichi_standalone_exe.ps1`
is run. PyInstaller is distributed under the GNU GPL with a bootloader
exception; review PyInstaller's license terms before publishing standalone
binary artifacts.

## Models

Koe Kichi can download Whisper-compatible model files through faster-whisper /
Hugging Face tooling. Model files are not part of this repository and may have
their own licenses and usage terms.

## Notes for Redistributors

- Do not commit or redistribute personal API keys, environment variables, user
  config files, dictionary files, logs, or history files.
- Bundled executable packages include dependency metadata under their internal
  package directories. Preserve that metadata when redistributing binaries.
- If dependency versions change, refresh this notice before publishing a
  release.
