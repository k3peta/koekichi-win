from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

APP_NAME = "KoeKichi"

WHISPER_MODEL_OPTIONS: list[tuple[str, str]] = [
    ("small", "small - CPU default, balanced"),
    ("medium", "medium - more accurate, slower on CPU"),
    ("large-v3", "large-v3 - highest accuracy, large and slow on CPU"),
    ("turbo", "turbo - large-v3 based, faster mainly on GPU"),
]

DEFAULT_CONFIG: dict[str, Any] = {
    "language": "ja",
    "sample_rate": 16000,
    "input_device": "auto",
    "record_key": "alt",
    "hold_to_record": False,
    "hold_record_key": "f8",
    "hold_start_delay_seconds": 0.2,
    "double_tap_to_toggle": True,
    "double_tap_interval_seconds": 0.45,
    "input_listener_backend": "polling",
    "middle_click_toggle_recording": False,
    "middle_click_suppress_native": False,
    "middle_click_debounce_seconds": 0.45,
    "paste_after_transcription": True,
    "copy_output_to_clipboard": True,
    "preserve_clipboard": True,
    "restore_clipboard_delay_seconds": 0.25,
    "max_record_seconds": 60,
    "hud_topmost": True,
    "whisper_model": "small",
    "whisper_device": "cpu",
    "whisper_compute_type": "int8",
    "whisper_cpu_fallback": True,
    "whisper_cpu_threads": "auto",
    "whisper_num_workers": 1,
    "whisper_prompt": "",
    "transcription_provider": "local_whisper",
    "gemini_model": "gemini-3.5-flash",
    "gemini_api_key_env": "GEMINI_API_KEY",
    "gemini_interactions_endpoint": "https://generativelanguage.googleapis.com/v1beta/interactions",
    "gemini_timeout_seconds": 45.0,
    "gemini_max_inline_audio_bytes": 18000000,
    "gemini_fallback_to_local": True,
    "gemini_preload_local_fallback": False,
    "gemini_transcription_prompt": "",
    "streaming_prefetch_enabled": True,
    "streaming_chunk_seconds": 4.0,
    "streaming_overlap_seconds": 0.8,
    "streaming_prompt_chars": 120,
    "streaming_min_tail_seconds": 1.0,
    "streaming_join_timeout_seconds": 12.0,
    "postprocess_mode": "local_punctuation",
    "openai_compatible_base_url": "",
    "openai_compatible_api_key_env": "OPENAI_API_KEY",
    "openai_compatible_model": "gpt-4.1-mini",
    "openai_compatible_timeout_seconds": 8.0,
    "openai_compatible_max_tokens": 512,
    "openai_compatible_custom_prompt": "",
    "launch_at_login": False,
    "preload_model_at_startup": False,
    "dictionary_path": "auto",
}


def app_data_dir() -> Path:
    root = os.environ.get("APPDATA")
    if root:
        return Path(root) / APP_NAME
    return Path.home() / "AppData" / "Roaming" / APP_NAME


def default_config_path() -> Path:
    return app_data_dir() / "config.json"


def default_dictionary_path() -> Path:
    return app_data_dir() / "dictionary.json"


def ensure_config(path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    if not config_path.exists():
        save_config(dict(DEFAULT_CONFIG), config_path)
    return config_path


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or ensure_config()
    config = dict(DEFAULT_CONFIG)
    if config_path.exists():
        with config_path.open("r", encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"Config must be an object: {config_path}")
        config.update(loaded)
    if config.get("dictionary_path") in ("", None, "auto"):
        config["dictionary_path"] = str(default_dictionary_path())
    else:
        config["dictionary_path"] = str(Path(str(config["dictionary_path"])).expanduser())
    return config


def save_config(config: dict[str, Any], path: Path | None = None) -> Path:
    config_path = path or default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return config_path

