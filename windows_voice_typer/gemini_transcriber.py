from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_GEMINI_PROMPT = (
    "Generate a clean Japanese transcript of the speech in this audio. "
    "Remove filler words and hesitation sounds such as えー, えっと, あのー, そのー, and あー. "
    "Keep the speaker's intended meaning and wording otherwise. "
    "Return only the transcript text. Do not summarize, translate, explain, "
    "add speaker labels, timestamps, markdown, or quotation marks. "
    "If there is no speech, return an empty string."
)


class GeminiAudioTranscriber:
    def __init__(
        self,
        *,
        model: str,
        api_key_env: str,
        endpoint: str,
        timeout_seconds: float,
        max_inline_audio_bytes: int,
        prompt: str,
    ):
        self.model = model
        self.api_key_env = api_key_env
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.max_inline_audio_bytes = max_inline_audio_bytes
        self.prompt = prompt or DEFAULT_GEMINI_PROMPT

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "GeminiAudioTranscriber":
        return cls(
            model=str(config.get("gemini_model", "gemini-3.5-flash")),
            api_key_env=str(config.get("gemini_api_key_env", "GEMINI_API_KEY")),
            endpoint=str(config.get("gemini_interactions_endpoint", "https://generativelanguage.googleapis.com/v1beta/interactions")),
            timeout_seconds=float(config.get("gemini_timeout_seconds", 45.0)),
            max_inline_audio_bytes=int(config.get("gemini_max_inline_audio_bytes", 18_000_000)),
            prompt=str(config.get("gemini_transcription_prompt", DEFAULT_GEMINI_PROMPT)),
        )

    def transcribe(self, audio_path: Path) -> str:
        api_key = get_api_key(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"{self.api_key_env} is not set")

        audio = audio_path.read_bytes()
        if len(audio) > self.max_inline_audio_bytes:
            raise RuntimeError(
                f"audio is too large for inline Gemini request: {len(audio)} bytes "
                f"> {self.max_inline_audio_bytes} bytes"
            )

        body = {
            "model": self.model,
            "input": [
                {"type": "text", "text": self.prompt},
                {
                    "type": "audio",
                    "data": base64.b64encode(audio).decode("ascii"),
                    "mime_type": _mime_type_for(audio_path),
                },
            ],
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini API error {error.code}: {_api_error_message(detail)}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Gemini API connection failed: {error}") from error

        text = _extract_output_text(payload)
        if text is None:
            raise RuntimeError("Gemini API response did not contain output_text")
        return sanitize_gemini_transcript(text)


def _mime_type_for(path: Path) -> str:
    if path.suffix.lower() == ".wav":
        return "audio/wav"
    detected, _encoding = mimetypes.guess_type(str(path))
    return detected or "application/octet-stream"


def _api_error_message(detail: str) -> str:
    try:
        data = json.loads(detail)
    except Exception:
        return detail.strip()[:500]
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        message = str(error.get("message", "")).strip()
        if message:
            return message
    return detail.strip()[:500]


def _extract_output_text(payload: Any) -> str | None:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message", "")).strip() or "unknown API error"
            raise RuntimeError(f"Gemini API error: {message}")
        for key in ("output_text", "outputText"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            text = _extract_generate_content_text(candidates)
            if text:
                return text
        for key in ("output", "outputs", "content", "parts", "response"):
            value = payload.get(key)
            text = _extract_nested_text(value)
            if text:
                return text
        steps = payload.get("steps")
        if isinstance(steps, list):
            text = _extract_steps_text(steps)
            if text:
                return text
    return _extract_nested_text(payload)


def _extract_generate_content_text(candidates: list[Any]) -> str | None:
    parts: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        for part in content.get("parts", []):
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    return "\n".join(parts).strip() or None


def _extract_steps_text(steps: list[Any]) -> str | None:
    parts: list[str] = []
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        content = step.get("content")
        text = _extract_nested_text(content)
        if text:
            parts.append(text)
    return "\n".join(parts).strip() or None


def _extract_nested_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [text for item in value if (text := _extract_nested_text(item))]
        return "\n".join(parts).strip() or None
    if isinstance(value, dict):
        direct = value.get("text")
        if isinstance(direct, str):
            return direct
        for key in ("output_text", "outputText", "content", "parts", "message"):
            text = _extract_nested_text(value.get(key))
            if text:
                return text
    return None


def get_api_key(env_name: str) -> str:
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
            value, _kind = winreg.QueryValueEx(handle, env_name)
        return str(value).strip()
    except Exception:
        return ""


def set_user_api_key(env_name: str, api_key: str) -> None:
    key = api_key.strip()
    if not key:
        raise ValueError("API key is empty")
    os.environ[env_name] = key
    if os.name != "nt":
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as handle:
        winreg.SetValueEx(handle, env_name, 0, winreg.REG_SZ, key)
    _broadcast_environment_change()


def _broadcast_environment_change() -> None:
    try:
        import ctypes

        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            5000,
            ctypes.byref(result),
        )
    except Exception:
        pass


def sanitize_gemini_transcript(text: str) -> str:
    result = text.strip()
    result = re.sub(r"^```(?:text|markdown)?\s*", "", result, flags=re.IGNORECASE)
    result = re.sub(r"\s*```$", "", result)
    for prefix in (
        "Transcript:",
        "Transcription:",
        "Output:",
        "出力:",
        "出力：",
        "文字起こし:",
        "文字起こし：",
        "書き起こし:",
        "書き起こし：",
        "発話内容:",
        "発話内容：",
    ):
        if result.startswith(prefix):
            result = result[len(prefix) :].strip()
    quote_pairs = (("「", "」"), ("『", "』"), ("“", "”"), ("‘", "’"), ('"', '"'), ("'", "'"))
    for left, right in quote_pairs:
        if len(result) >= len(left) + len(right) and result.startswith(left) and result.endswith(right):
            result = result[len(left) : -len(right)].strip()
    result = _remove_japanese_fillers(result)
    return result


def _remove_japanese_fillers(text: str) -> str:
    result = text
    fillers = r"(?:えーっと|えっと|えーと|えー|あー|あのー|あの|そのー|その)"
    result = re.sub(rf"(^|[、。！？!?，,\s]){fillers}(?=[、。！？!?，,\s]|$)", r"\1", result)
    result = re.sub(r"[、，]\s*[、，]+", "、", result)
    result = re.sub(r"^\s*[、，]\s*", "", result)
    return result.strip()
