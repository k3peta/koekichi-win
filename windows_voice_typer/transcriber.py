from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any


class FasterWhisperTranscriber:
    def __init__(
        self,
        model: str,
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "ja",
        cpu_fallback: bool = True,
        cpu_threads: int | str | None = "auto",
        num_workers: int = 1,
        beam_size: int = 3,
        condition_on_previous_text: bool = False,
    ):
        self.model = model
        self.device = device or "cpu"
        self.compute_type = compute_type or "int8"
        self.language = language
        self.cpu_fallback = cpu_fallback
        self.cpu_threads = _resolve_cpu_threads(cpu_threads)
        self.num_workers = max(1, int(num_workers or 1))
        self.beam_size = max(1, int(beam_size or 1))
        self.condition_on_previous_text = bool(condition_on_previous_text)
        self._model: Any | None = None
        self._model_lock = threading.Lock()
        self._transcribe_lock = threading.Lock()

    def ensure_model(self) -> None:
        self._ensure_model()

    def transcribe(self, path: str | Path, prompt: str = "", hotwords: str | None = None) -> str:
        return "".join(segment["text"] for segment in self.transcribe_segments(path, prompt=prompt, hotwords=hotwords)).strip()

    def transcribe_segments(self, path: str | Path, prompt: str = "", hotwords: str | None = None) -> list[dict[str, Any]]:
        model = self._ensure_model()
        with self._transcribe_lock:
            segments, _info = model.transcribe(
                str(path),
                language=self.language,
                initial_prompt=prompt or None,
                hotwords=hotwords or None,
                vad_filter=True,
                beam_size=self.beam_size,
                condition_on_previous_text=self.condition_on_previous_text,
            )
            return [
                {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": str(segment.text),
                }
                for segment in segments
            ]

    def _ensure_model(self) -> Any:
        with self._model_lock:
            if self._model is None:
                try:
                    self._model = self._load_model(self.device, self.compute_type)
                except Exception as error:
                    if str(self.device).lower() == "cpu" or not self.cpu_fallback:
                        raise RuntimeError(
                            "Could not load faster-whisper. Check the model name, network/model cache, "
                            "and requirements-windows.txt installation."
                        ) from error
                    print(f"whisper load failed on {self.device}; falling back to cpu/int8: {error}")
                    self.device = "cpu"
                    self.compute_type = "int8"
                    self._model = self._load_model(self.device, self.compute_type)
            return self._model

    def _load_model(self, device: str, compute_type: str) -> Any:
        from faster_whisper import WhisperModel

        return WhisperModel(
            self.model,
            device=device,
            compute_type=compute_type,
            cpu_threads=self.cpu_threads,
            num_workers=self.num_workers,
        )


def _resolve_cpu_threads(value: int | str | None) -> int:
    logical = os.cpu_count() or 4
    auto_value = max(1, min(4, logical - 2))
    if value in (None, "", "auto"):
        return auto_value
    try:
        requested = int(value)
    except (TypeError, ValueError):
        return auto_value
    return max(1, min(requested, max(1, logical - 1)))
