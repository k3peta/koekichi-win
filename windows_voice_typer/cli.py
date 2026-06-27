from __future__ import annotations

import argparse
import platform
import sys
import time
from pathlib import Path

from .app import WindowsVoiceTyperApp
from .config import default_config_path
from .config import ensure_config
from .config import load_config
from .config import save_config
from .dictionary import VoiceDictionary
from .gemini_transcriber import GeminiAudioTranscriber
from .gemini_transcriber import get_api_key
from .postprocess import postprocess
from .transcriber import FasterWhisperTranscriber


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="koe-kichi-win")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create config and dictionary files.")
    sub.add_parser("run", help="Run the Windows voice typer.")
    sub.add_parser("configure", help="Choose microphone and activation key.")
    setup = sub.add_parser("setup", help="Run first setup checks.")
    setup.add_argument("--no-download", action="store_true", help="Do not download the Whisper model.")
    setup.add_argument("--model-timeout-seconds", type=float, default=600.0)
    setup.add_argument("--configure", action="store_true", help="Choose microphone and activation key before setup checks.")
    diagnose = sub.add_parser("diagnose", help="Check Python and audio devices.")
    diagnose.add_argument("--record-seconds", type=float, default=0.0)
    diagnose.add_argument("--check-model", action="store_true", help="Load the Whisper model. This may download it.")
    process = sub.add_parser("process", help="Run dictionary and postprocess on text.")
    process.add_argument("text")
    transcribe = sub.add_parser("transcribe-file", help="Transcribe an audio file.")
    transcribe.add_argument("path")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    config_path = ensure_config()
    config = load_config(config_path)
    dictionary = VoiceDictionary(str(config["dictionary_path"]))
    dictionary.ensure()

    if args.command == "init":
        save_config(config, config_path)
        print(f"config: {config_path}")
        print(f"dictionary: {dictionary.path}")
        return 0
    if args.command == "diagnose":
        return diagnose(config, record_seconds=args.record_seconds, check_model=args.check_model)
    if args.command == "setup":
        from .setup import run_setup_check

        return run_setup_check(
            download=not args.no_download,
            model_timeout_seconds=args.model_timeout_seconds,
            configure=bool(args.configure),
        )
    if args.command == "configure":
        from .setup import run_initial_settings

        return run_initial_settings()
    if args.command == "process":
        processed = dictionary.process(args.text)
        result = postprocess(processed, config)
        print(result.text)
        if result.error:
            print(f"fallback: {result.error}", file=sys.stderr)
        return 0
    if args.command == "transcribe-file":
        raw = transcribe_file_with_config(Path(args.path), config)
        processed = dictionary.process(raw)
        result = postprocess(processed, config)
        print(f"raw: {raw}")
        print(f"out: {result.text}")
        return 0
    if args.command == "run":
        WindowsVoiceTyperApp(config).run_forever()
        return 0
    parser.print_help(sys.stderr)
    return 2


def diagnose(config: dict, record_seconds: float = 0.0, check_model: bool = False) -> int:
    print(f"system: {platform.platform()}")
    print(f"python: {sys.executable}")
    print(f"config: {default_config_path()}")
    print(f"dictionary: {config.get('dictionary_path')}")
    print(
        "whisper: "
        f"model={config.get('whisper_model')} "
        f"device={config.get('whisper_device')} "
        f"compute_type={config.get('whisper_compute_type')} "
        f"cpu_fallback={config.get('whisper_cpu_fallback')} "
        f"cpu_threads={config.get('whisper_cpu_threads', 'auto')} "
        f"num_workers={config.get('whisper_num_workers', 1)}"
    )
    print(f"postprocess_mode: {config.get('postprocess_mode')}")
    print(f"input_device: {config.get('input_device')}")
    print(f"record_key: {config.get('record_key')}")
    print(f"transcription_provider: {config.get('transcription_provider')}")
    print(f"gemini_model: {config.get('gemini_model')}")
    gemini_env = str(config.get("gemini_api_key_env", "GEMINI_API_KEY"))
    print(f"gemini_api_key_env: {gemini_env} ({'set' if get_api_key(gemini_env) else 'not set'})")
    try:
        import sounddevice as sd

        print("audio_devices:")
        for index, device in enumerate(sd.query_devices()):
            max_inputs = int(device.get("max_input_channels", 0))
            marker = "input" if max_inputs > 0 else "output"
            print(f"  - {index}: {device['name']} ({marker}, in={max_inputs})")
    except Exception as error:
        print(f"audio_check_failed: {error}")
        return 1

    if record_seconds > 0:
        from .recorder import Recorder

        recorder = Recorder(sample_rate=int(config.get("sample_rate", 16000)), device=config.get("input_device", "auto"))
        recorder.start()
        time.sleep(record_seconds)
        path = recorder.stop_to_wav()
        print(f"recording_test_wav: {path}")
        path.unlink(missing_ok=True)
    if check_model:
        transcriber = FasterWhisperTranscriber(
            model=str(config.get("whisper_model", "small")),
            device=str(config.get("whisper_device", "cpu")),
            compute_type=str(config.get("whisper_compute_type", "int8")),
            language=str(config.get("language", "ja")),
            cpu_fallback=bool(config.get("whisper_cpu_fallback", True)),
            cpu_threads=config.get("whisper_cpu_threads", "auto"),
            num_workers=int(config.get("whisper_num_workers", 1) or 1),
        )
        transcriber._ensure_model()
        print("whisper_model_loaded: true")
    return 0


def transcribe_file_with_config(path: Path, config: dict) -> str:
    provider = str(config.get("transcription_provider", "local_whisper")).strip().lower()
    if provider == "gemini_audio":
        try:
            raw = GeminiAudioTranscriber.from_config(config).transcribe(path)
            if raw:
                return raw
            print("gemini fallback: empty result", file=sys.stderr)
        except Exception as error:
            if not bool(config.get("gemini_fallback_to_local", True)):
                raise
            print(f"gemini fallback: {error}", file=sys.stderr)
    transcriber = FasterWhisperTranscriber(
        model=str(config.get("whisper_model", "small")),
        device=str(config.get("whisper_device", "cpu")),
        compute_type=str(config.get("whisper_compute_type", "int8")),
        language=str(config.get("language", "ja")),
        cpu_fallback=bool(config.get("whisper_cpu_fallback", True)),
        cpu_threads=config.get("whisper_cpu_threads", "auto"),
        num_workers=int(config.get("whisper_num_workers", 1) or 1),
    )
    return transcriber.transcribe(path, prompt=str(config.get("whisper_prompt", "")))


if __name__ == "__main__":
    raise SystemExit(main())


