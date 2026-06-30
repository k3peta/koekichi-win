from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import default_config_path
from .config import ensure_config
from .config import load_config
from .config import POSTPROCESS_MODE_OPTIONS
from .config import save_config
from .config import WHISPER_BEAM_SIZE_OPTIONS
from .config import WHISPER_MODEL_OPTIONS
from .dictionary import VoiceDictionary


def run_setup_check(download: bool = True, model_timeout_seconds: float = 600.0, configure: bool = False) -> int:
    _configure_console()
    config_path = ensure_config()
    config = load_config(config_path)
    dictionary = VoiceDictionary(str(config["dictionary_path"]))
    dictionary.ensure()

    print("Koe Kichi setup check")
    print("=====================")
    print(f"config: {config_path}")
    print(f"dictionary: {dictionary.path}")
    print("")

    if configure:
        config = _run_initial_settings(config, config_path)
        print("")

    audio_ok = _check_audio(config)
    print("")
    model_ok = _check_model(config, download=download, timeout_seconds=model_timeout_seconds)
    print("")

    if audio_ok and model_ok:
        print("Setup check passed. Koe Kichi is ready.")
        return 0

    print("Setup check found a problem. See the messages above.")
    return 1


def run_initial_settings() -> int:
    _configure_console()
    config_path = ensure_config()
    config = load_config(config_path)
    dictionary = VoiceDictionary(str(config["dictionary_path"]))
    dictionary.ensure()
    print("Koe Kichi settings")
    print("==================")
    print(f"config: {config_path}")
    print("")
    _run_initial_settings(config, config_path)
    return 0


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def _check_audio(config: dict[str, Any]) -> bool:
    print("[1/2] Audio device check")
    try:
        import sounddevice as sd
    except Exception as error:
        print(f"sounddevice import failed: {error}")
        return False

    configured = config.get("input_device", "auto")
    print(f"configured input_device: {configured}")
    try:
        devices = list(sd.query_devices())
    except Exception as error:
        print(f"audio device query failed: {error}")
        return False

    input_indexes: list[int] = []
    for index, device in enumerate(devices):
        max_inputs = int(device.get("max_input_channels", 0))
        if max_inputs <= 0:
            continue
        input_indexes.append(index)
        marker = "* " if configured == index or str(configured) == str(index) else "  "
        print(f"{marker}{index}: {device.get('name', '')} (inputs={max_inputs})")

    if not input_indexes:
        print("No input devices were found.")
        return False
    if configured in (None, "", "auto"):
        print("Audio check passed. Koe Kichi will use the default input device.")
        return True
    try:
        configured_index = int(configured)
    except Exception:
        print("input_device must be auto or a numeric device index.")
        return False
    if configured_index not in input_indexes:
        print(f"Configured input device {configured_index} was not found.")
        return False

    print("Audio check passed.")
    return True


def _run_initial_settings(config: dict[str, Any], config_path: Any) -> dict[str, Any]:
    print("[Initial settings]")
    print("Choose a microphone, activation key, Whisper accuracy, transcription backend, correction mode, and login startup behavior.")
    print("Press Enter to keep the current value.")
    print("")
    config = dict(config)
    selected_device = _choose_input_device(config.get("input_device", "auto"))
    if selected_device is not None:
        config["input_device"] = selected_device
    selected_key = _choose_record_key(str(config.get("record_key", "alt")))
    if selected_key:
        config["record_key"] = selected_key
        config["hold_to_record"] = False
        config["double_tap_to_toggle"] = True
    config["whisper_model"] = _choose_whisper_model(str(config.get("whisper_model", "small") or "small"))
    config["whisper_beam_size"] = _choose_whisper_beam_size(int(config.get("whisper_beam_size", 3) or 3))
    config["whisper_condition_on_previous_text"] = _choose_previous_text_context(
        bool(config.get("whisper_condition_on_previous_text", False))
    )
    selected_provider = _choose_transcription_provider(str(config.get("transcription_provider", "local_whisper")))
    config["transcription_provider"] = selected_provider
    if selected_provider == "gemini_audio":
        config["gemini_api_key_env"] = _choose_gemini_api_key_env(str(config.get("gemini_api_key_env", "GEMINI_API_KEY")))
    postprocess_mode = _choose_postprocess_mode(str(config.get("postprocess_mode", "local_punctuation") or "local_punctuation"))
    config["postprocess_mode"] = postprocess_mode
    if postprocess_mode.startswith("openai_compatible_"):
        config["openai_compatible_base_url"] = _choose_openai_compatible_base_url(
            str(config.get("openai_compatible_base_url", "") or "")
        )
        config["openai_compatible_model"] = _choose_openai_compatible_model(
            str(config.get("openai_compatible_model", "gpt-4.1-mini") or "gpt-4.1-mini")
        )
        config["openai_compatible_api_key_env"] = _choose_openai_compatible_api_key_env(
            str(config.get("openai_compatible_api_key_env", "OPENAI_API_KEY") or "OPENAI_API_KEY")
        )
    launch_at_login = _choose_launch_at_login(bool(config.get("launch_at_login", False)))
    config["launch_at_login"] = launch_at_login
    config["initial_settings_completed"] = True
    save_config(config, config_path)
    startup_result = _apply_launch_at_login(launch_at_login)
    print(
        "Saved settings: "
        f"input_device={config.get('input_device')} "
        f"record_key={config.get('record_key')} "
        f"whisper_model={config.get('whisper_model')} "
        f"whisper_beam_size={config.get('whisper_beam_size')} "
        f"postprocess_mode={config.get('postprocess_mode')} "
        f"launch_at_login={config.get('launch_at_login')} "
        f"transcription_provider={config.get('transcription_provider')}"
    )
    if startup_result:
        print(startup_result)
    print("Restart Koe Kichi if it is already running.")
    return load_config(config_path)


def _choose_input_device(current: Any) -> Any | None:
    try:
        import sounddevice as sd
        devices = list(sd.query_devices())
    except Exception as error:
        print(f"Microphone selection skipped: {error}")
        return None

    inputs: list[tuple[int, str, int]] = []
    for index, device in enumerate(devices):
        max_inputs = int(device.get("max_input_channels", 0))
        if max_inputs > 0:
            inputs.append((index, str(device.get("name", "")), max_inputs))
    if not inputs:
        print("No microphones were found. Keeping input_device=auto.")
        return "auto"

    print("Microphones:")
    print("  A: Auto / Windows default microphone")
    for index, name, max_inputs in inputs:
        marker = " *" if str(current) == str(index) else ""
        print(f"  {index}: {name} (inputs={max_inputs}){marker}")
    choice = input("Microphone [A or number, Enter=current]: ").strip()
    if not choice:
        return current if current not in (None, "") else "auto"
    if choice.lower() in ("a", "auto"):
        return "auto"
    try:
        selected = int(choice)
    except ValueError:
        print("Invalid microphone choice. Keeping the current value.")
        return current
    if selected not in {index for index, _name, _inputs in inputs}:
        print("That microphone number was not found. Keeping the current value.")
        return current
    return selected


def _choose_record_key(current: str) -> str:
    choices = [
        ("alt", "Alt double-tap (recommended, keeps browser focus best)"),
        ("ctrl", "Ctrl double-tap"),
        ("shift", "Shift double-tap"),
        ("f9", "F9 double-tap"),
    ]
    print("")
    print("Activation key:")
    for number, (key, label) in enumerate(choices, start=1):
        marker = " *" if current.lower() == key else ""
        print(f"  {number}: {label}{marker}")
    choice = input("Activation key [1-4, Enter=current]: ").strip()
    if not choice:
        return current or "alt"
    try:
        index = int(choice) - 1
    except ValueError:
        print("Invalid activation key choice. Keeping the current value.")
        return current
    if not 0 <= index < len(choices):
        print("Invalid activation key choice. Keeping the current value.")
        return current
    return choices[index][0]


def _choose_whisper_model(current: str) -> str:
    choices = list(WHISPER_MODEL_OPTIONS)
    if current and current not in {model for model, _label in choices}:
        choices.append((current, f"{current} - current custom model"))
    print("")
    print("Whisper model:")
    for number, (model, label) in enumerate(choices, start=1):
        marker = " *" if current == model else ""
        print(f"  {number}: {label}{marker}")
    choice = input(f"Whisper model [1-{len(choices)}, Enter=current]: ").strip()
    if not choice:
        return current or "small"
    try:
        index = int(choice) - 1
    except ValueError:
        print("Invalid Whisper model choice. Keeping the current value.")
        return current
    if not 0 <= index < len(choices):
        print("Invalid Whisper model choice. Keeping the current value.")
        return current
    return choices[index][0]


def _choose_whisper_beam_size(current: int) -> int:
    choices = list(WHISPER_BEAM_SIZE_OPTIONS)
    if current and current not in {value for value, _label in choices}:
        choices.append((current, f"{current} - current custom value"))
    print("")
    print("Whisper accuracy:")
    for number, (value, label) in enumerate(choices, start=1):
        marker = " *" if int(current or 0) == int(value) else ""
        print(f"  {number}: {label}{marker}")
    choice = input(f"Whisper accuracy [1-{len(choices)}, Enter=current]: ").strip()
    if not choice:
        return current or 3
    try:
        index = int(choice) - 1
    except ValueError:
        print("Invalid Whisper accuracy choice. Keeping the current value.")
        return current
    if not 0 <= index < len(choices):
        print("Invalid Whisper accuracy choice. Keeping the current value.")
        return current
    return int(choices[index][0])


def _choose_previous_text_context(current: bool) -> bool:
    label = "yes" if current else "no"
    choice = input(f"Use previous text context in Whisper? [y/n, Enter={label}]: ").strip().lower()
    if not choice:
        return current
    if choice in ("y", "yes", "1", "true", "on"):
        return True
    if choice in ("n", "no", "0", "false", "off"):
        return False
    print("Invalid context choice. Keeping the current value.")
    return current


def _choose_launch_at_login(current: bool) -> bool:
    label = "yes" if current else "no"
    choice = input(f"Launch Koe Kichi when you sign in? [y/n, Enter={label}]: ").strip().lower()
    if not choice:
        return current
    if choice in ("y", "yes", "1", "true", "on"):
        return True
    if choice in ("n", "no", "0", "false", "off"):
        return False
    print("Invalid login startup choice. Keeping the current value.")
    return current


def _choose_transcription_provider(current: str) -> str:
    choices = [
        ("local_whisper", "Local Whisper on this PC (recommended, private, no API cost)"),
        ("gemini_audio", "Gemini API one-call audio transcription (experimental, requires GEMINI_API_KEY)"),
    ]
    print("")
    print("Transcription backend:")
    for number, (provider, label) in enumerate(choices, start=1):
        marker = " *" if current.lower() == provider else ""
        print(f"  {number}: {label}{marker}")
    choice = input("Transcription backend [1-2, Enter=current]: ").strip()
    if not choice:
        return current or "local_whisper"
    try:
        index = int(choice) - 1
    except ValueError:
        print("Invalid transcription backend choice. Keeping the current value.")
        return current
    if not 0 <= index < len(choices):
        print("Invalid transcription backend choice. Keeping the current value.")
        return current
    return choices[index][0]


def _choose_postprocess_mode(current: str) -> str:
    choices = list(POSTPROCESS_MODE_OPTIONS)
    if current and current not in {mode for mode, _label in choices}:
        choices.append((current, f"{current} - current custom mode"))
    print("")
    print("Text correction:")
    for number, (mode, label) in enumerate(choices, start=1):
        marker = " *" if current.lower() == mode.lower() else ""
        print(f"  {number}: {label}{marker}")
    choice = input(f"Text correction [1-{len(choices)}, Enter=current]: ").strip()
    if not choice:
        return current or "local_punctuation"
    try:
        index = int(choice) - 1
    except ValueError:
        print("Invalid text correction choice. Keeping the current value.")
        return current
    if not 0 <= index < len(choices):
        print("Invalid text correction choice. Keeping the current value.")
        return current
    return choices[index][0]


def _choose_openai_compatible_base_url(current: str) -> str:
    label = current or "https://api.openai.com/v1"
    choice = input(f"AI correction OpenAI-compatible base URL [Enter={label}]: ").strip()
    return choice or current


def _choose_openai_compatible_model(current: str) -> str:
    current = current or "gpt-4.1-mini"
    choice = input(f"AI correction model [Enter={current}]: ").strip()
    return choice or current


def _choose_openai_compatible_api_key_env(current: str) -> str:
    current = current or "OPENAI_API_KEY"
    choice = input(f"AI correction API key environment variable [Enter={current}]: ").strip()
    return choice or current


def _choose_gemini_api_key_env(current: str) -> str:
    current = current or "GEMINI_API_KEY"
    choice = input(f"Gemini API key environment variable [Enter={current}]: ").strip()
    return choice or current


def _apply_launch_at_login(enabled: bool) -> str:
    startup_dir = _startup_dir()
    shortcut_path = startup_dir / "Koe Kichi.lnk"
    try:
        if enabled:
            _create_startup_shortcut(shortcut_path)
            return f"Login startup enabled: {shortcut_path}"
        if shortcut_path.exists():
            shortcut_path.unlink()
        return "Login startup disabled."
    except Exception as error:
        return f"Could not update login startup shortcut: {error}"


def _startup_dir() -> Path:
    root = os.environ.get("APPDATA")
    if root:
        return Path(root) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _create_startup_shortcut(path: Path) -> None:
    frozen = bool(getattr(sys, "frozen", False))
    target = Path(sys.executable)
    if frozen:
        app_dir = target.resolve().parent
        arguments = ""
    else:
        app_dir = Path(__file__).resolve().parent.parent
        pythonw = target.with_name("pythonw.exe")
        if pythonw.exists():
            target = pythonw
        arguments = "-m windows_voice_typer.cli run"
    icon = app_dir / "assets" / "koe-kichi.ico"
    script = "\n".join(
        [
            f"$Path = {_ps_string(str(path))}",
            f"$Target = {_ps_string(str(target))}",
            f"$Arguments = {_ps_string(arguments)}",
            f"$WorkingDirectory = {_ps_string(str(app_dir))}",
            "$Description = 'Run Koe Kichi at login'",
            f"$Icon = {_ps_string(str(icon))}",
            "$Dir = Split-Path -Parent $Path",
            "New-Item -ItemType Directory -Force -Path $Dir | Out-Null",
            "$Shell = New-Object -ComObject WScript.Shell",
            "$Shortcut = $Shell.CreateShortcut($Path)",
            "$Shortcut.TargetPath = $Target",
            "$Shortcut.Arguments = $Arguments",
            "$Shortcut.WorkingDirectory = $WorkingDirectory",
            "$Shortcut.Description = $Description",
            "if (Test-Path -LiteralPath $Icon) { $Shortcut.IconLocation = $Icon } else { $Shortcut.IconLocation = $Target }",
            "$Shortcut.Save()",
        ]
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        **_hidden_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(detail or f"PowerShell exited with code {completed.returncode}")


def _ps_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _check_model(config: dict[str, Any], download: bool, timeout_seconds: float) -> bool:
    print("[2/2] Whisper model check")
    model = str(config.get("whisper_model", "small"))
    device = str(config.get("whisper_device", "cpu"))
    compute_type = str(config.get("whisper_compute_type", "int8"))
    print(f"model={model} device={device} compute_type={compute_type}")

    local_result = _try_load_model(model, device, compute_type, local_files_only=True, timeout_seconds=90.0)
    if local_result == "ok":
        print("Model is already cached and loadable.")
        return True

    print(f"Local model check did not pass: {local_result}")
    if not download:
        print("Download is disabled for this setup check.")
        return False

    print("Downloading/loading the model now. The first run can take several minutes.")
    download_result = _try_load_model(
        model,
        device,
        compute_type,
        local_files_only=False,
        timeout_seconds=timeout_seconds,
    )
    if download_result == "ok":
        print("Model download/load passed.")
        return True

    print(f"Model download/load failed: {download_result}")
    return False


def _try_load_model(
    model: str,
    device: str,
    compute_type: str,
    local_files_only: bool,
    timeout_seconds: float,
) -> str:
    env = os.environ.copy()
    env["KOEKICHI_MODEL"] = model
    env["KOEKICHI_DEVICE"] = device
    env["KOEKICHI_COMPUTE_TYPE"] = compute_type
    env["KOEKICHI_LOCAL_FILES_ONLY"] = "1" if local_files_only else "0"
    code = (
        "import os\n"
        "from faster_whisper import WhisperModel\n"
        "local = os.environ.get('KOEKICHI_LOCAL_FILES_ONLY') == '1'\n"
        "WhisperModel(\n"
        "    os.environ.get('KOEKICHI_MODEL', 'small'),\n"
        "    device=os.environ.get('KOEKICHI_DEVICE', 'cpu'),\n"
        "    compute_type=os.environ.get('KOEKICHI_COMPUTE_TYPE', 'int8'),\n"
        "    local_files_only=local,\n"
        ")\n"
        "print('ok')\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            env=env,
            text=True,
            timeout=timeout_seconds,
            **_hidden_subprocess_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return f"timed out after {int(timeout_seconds)} seconds"
    except Exception as error:
        return str(error)

    output = (completed.stdout or "").strip()
    error = (completed.stderr or "").strip()
    if completed.returncode == 0 and output.endswith("ok"):
        return "ok"
    if error:
        return error.splitlines()[-1]
    if output:
        return output.splitlines()[-1]
    return f"process exited with code {completed.returncode}"
