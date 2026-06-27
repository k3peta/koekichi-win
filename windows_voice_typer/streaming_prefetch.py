from __future__ import annotations

import threading
import time
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


LogCallback = Callable[[str], None]


@dataclass
class PrefetchWindow:
    index: int
    start_seconds: float
    end_seconds: float
    transcribe_seconds: float
    segments: list[dict[str, Any]]


class StreamingPrefetchSession:
    def __init__(
        self,
        *,
        recorder: Any,
        transcriber: Any,
        config: dict[str, Any],
        log: LogCallback,
    ):
        self.recorder = recorder
        self.transcriber = transcriber
        self.log = log
        self.chunk_seconds = float(config.get("streaming_chunk_seconds", 4.0))
        self.overlap_seconds = float(config.get("streaming_overlap_seconds", 0.8))
        self.prompt_chars = int(config.get("streaming_prompt_chars", 120))
        self.min_tail_seconds = float(config.get("streaming_min_tail_seconds", 1.0))
        self.max_join_seconds = float(config.get("streaming_join_timeout_seconds", 12.0))
        self._sample_rate = int(config.get("sample_rate", 16000))
        self._chunk_samples = max(1, int(self.chunk_seconds * self._sample_rate))
        overlap_samples = max(0, int(self.overlap_seconds * self._sample_rate))
        self._stride_samples = max(1, self._chunk_samples - overlap_samples)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._windows: list[PrefetchWindow] = []
        self._next_start_sample = 0
        self._prompt = str(config.get("whisper_prompt", ""))
        self._started_at = time.perf_counter()
        self._errors: list[str] = []

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="KoeKichiStreamingPrefetch", daemon=True)
        self._thread.start()
        self.log(
            "streaming prefetch started: "
            f"chunk={self.chunk_seconds:g}s overlap={self.overlap_seconds:g}s prompt_chars={self.prompt_chars}"
        )

    def finish(self) -> str:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self.max_join_seconds)
        if thread is not None and thread.is_alive():
            self.log("streaming prefetch fallback: worker did not stop in time")
            return ""

        audio = self.recorder.snapshot_audio()
        if audio is None:
            self.log("streaming prefetch fallback: no audio snapshot")
            return ""

        total_samples = int(audio.shape[0])
        if total_samples < self._chunk_samples and not self._windows:
            seconds = total_samples / float(self._sample_rate)
            self.log(f"streaming prefetch skipped: audio too short ({seconds:.2f}s)")
            return ""

        while self._next_start_sample < total_samples:
            end_sample = min(total_samples, self._next_start_sample + self._chunk_samples)
            duration = (end_sample - self._next_start_sample) / float(self._sample_rate)
            if duration < self.min_tail_seconds and self._windows:
                break
            self._process_window(audio, self._next_start_sample, end_sample)
            if end_sample >= total_samples:
                break
            self._next_start_sample += self._stride_samples

        text = self._merged_text(total_samples / float(self._sample_rate))
        with self._lock:
            window_count = len(self._windows)
            compute_seconds = sum(window.transcribe_seconds for window in self._windows)
        elapsed = time.perf_counter() - self._started_at
        self.log(
            "streaming prefetch result: "
            f"windows={window_count} compute={compute_seconds:.2f}s elapsed={elapsed:.2f}s chars={len(text)}"
        )
        return text.strip()

    def cancel(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

    def _run(self) -> None:
        while not self._stop_event.wait(0.15):
            audio = self.recorder.snapshot_audio()
            if audio is None:
                continue
            total_samples = int(audio.shape[0])
            while self._next_start_sample + self._chunk_samples <= total_samples:
                start_sample = self._next_start_sample
                end_sample = start_sample + self._chunk_samples
                if not self._process_window(audio, start_sample, end_sample):
                    return
                self._next_start_sample += self._stride_samples

    def _process_window(self, audio: Any, start_sample: int, end_sample: int) -> bool:
        chunk = audio[start_sample:end_sample]
        if chunk.shape[0] <= 0:
            return True
        path: Path | None = None
        try:
            path = self.recorder.audio_to_wav(chunk)
            started = time.perf_counter()
            segments = self.transcriber.transcribe_segments(path, prompt=self._prompt)
            seconds = time.perf_counter() - started
        except Exception as error:
            message = f"streaming prefetch window failed: {error}"
            self._errors.append(message)
            self.log(message)
            return False
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass

        start_seconds = start_sample / float(self._sample_rate)
        end_seconds = end_sample / float(self._sample_rate)
        with self._lock:
            if any(window.start_seconds == start_seconds for window in self._windows):
                return True
            index = len(self._windows)
            self._windows.append(
                PrefetchWindow(
                    index=index,
                    start_seconds=start_seconds,
                    end_seconds=end_seconds,
                    transcribe_seconds=seconds,
                    segments=segments,
                )
            )
            self._prompt = self._merged_text_unlocked(end_seconds)[-self.prompt_chars :]
        self.log(
            "streaming prefetch window: "
            f"{start_seconds:.2f}-{end_seconds:.2f}s segments={len(segments)} seconds={seconds:.2f}"
        )
        return True

    def _merged_text(self, total_seconds: float) -> str:
        with self._lock:
            return self._merged_text_unlocked(total_seconds)

    def _merged_text_unlocked(self, total_seconds: float) -> str:
        windows = sorted(self._windows, key=lambda item: item.start_seconds)
        if not windows:
            return ""
        parts: list[tuple[float, str]] = []
        for position, window in enumerate(windows):
            left = window.start_seconds if position == 0 else window.start_seconds + self.overlap_seconds / 2.0
            right = window.end_seconds if position == len(windows) - 1 else window.end_seconds - self.overlap_seconds / 2.0
            right = min(right, total_seconds)
            for segment in window.segments:
                text = str(segment.get("text", ""))
                if not text.strip():
                    continue
                start = window.start_seconds + float(segment.get("start", 0.0))
                end = window.start_seconds + float(segment.get("end", 0.0))
                center = (start + end) / 2.0
                if left <= center <= right:
                    parts.append((start, text))
        return _overlap_merge([text for _start, text in sorted(parts, key=lambda item: item[0])])


def _overlap_merge(parts: list[str]) -> str:
    output = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not output:
            output = part
            continue
        if _part_already_covered(output, part):
            continue
        cut = _best_overlap_cut(output, part)
        if cut > 0 and output[-1:] in "、。" and _continues_sentence(part[cut:]):
            output = output[:-1]
        output += part[cut:]
    return _collapse_repeated_runs(output)


def _best_overlap_cut(output: str, part: str) -> int:
    for size in range(min(len(output), len(part), 80), 2, -1):
        prefix = _normalize_for_overlap(part[:size])
        if len(prefix) < 3:
            continue
        tail = _normalize_for_overlap(output[-(size + 40) :])
        if tail.endswith(prefix):
            return size
    return 0


def _part_already_covered(output: str, part: str) -> bool:
    normalized_part = _normalize_for_overlap(part)
    if len(normalized_part) < 4:
        return False
    return normalized_part in _normalize_for_overlap(output[-180:])


def _normalize_for_overlap(text: str) -> str:
    return re.sub(r"[\s、。！？!?.,，．]+", "", text).casefold()


def _continues_sentence(text: str) -> bool:
    return re.match(r"[一-龠々〆ヵヶぁ-んァ-ンA-Za-z0-9]", text.lstrip()) is not None


def _collapse_repeated_runs(text: str) -> str:
    result = text
    previous = None
    while previous != result:
        previous = result
        result = re.sub(r"(?<![A-Za-z])([A-Z]{2,10})\1(?![A-Za-z])", r"\1", result)
        result = re.sub(r"(?<![一-龠])([一-龠]{2,6})\1(?![一-龠])", r"\1", result)
        result = re.sub(r"(?<![ァ-ンー])([ァ-ンー]{3,10})\1(?![ァ-ンー])", r"\1", result)
    return result
