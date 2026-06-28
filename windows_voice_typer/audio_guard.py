from __future__ import annotations

import math
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AudioActivitySummary:
    seconds: float
    rms: float
    peak: float
    active_seconds: float
    active_ratio: float
    sample_rate: int


@dataclass(frozen=True)
class AudioGuardDecision:
    skip: bool
    reason: str = ""


def wav_activity_summary(
    path: str | Path,
    *,
    frame_ms: float = 30.0,
    active_threshold: float = 0.01,
) -> AudioActivitySummary:
    with wave.open(str(path), "rb") as handle:
        channels = max(1, int(handle.getnchannels()))
        sample_width = int(handle.getsampwidth())
        sample_rate = int(handle.getframerate())
        frame_count = int(handle.getnframes())
        data = handle.readframes(frame_count)

    seconds = frame_count / float(sample_rate) if sample_rate else 0.0
    if not data or sample_width != 2 or sample_rate <= 0:
        return AudioActivitySummary(seconds, 0.0, 0.0, 0.0, 0.0, sample_rate)

    samples = array("h")
    samples.frombytes(data)
    if not samples:
        return AudioActivitySummary(seconds, 0.0, 0.0, 0.0, 0.0, sample_rate)

    if channels > 1:
        mono = array("h")
        for index in range(0, len(samples), channels):
            values = samples[index : index + channels]
            if values:
                mono.append(int(sum(values) / len(values)))
        samples = mono

    peak_int = max(abs(sample) for sample in samples)
    square_sum = sum(sample * sample for sample in samples)
    rms = math.sqrt(square_sum / max(1, len(samples))) / 32768.0
    peak = peak_int / 32768.0

    frame_samples = max(1, int(sample_rate * frame_ms / 1000.0))
    active_frames = 0
    frame_total = 0
    threshold_int = int(max(0.0, active_threshold) * 32768)
    for start in range(0, len(samples), frame_samples):
        frame = samples[start : start + frame_samples]
        if not frame:
            continue
        frame_total += 1
        if max(abs(sample) for sample in frame) >= threshold_int:
            active_frames += 1
    active_seconds = active_frames * frame_samples / float(sample_rate)
    active_seconds = min(seconds, active_seconds)
    active_ratio = active_seconds / seconds if seconds > 0 else 0.0
    return AudioActivitySummary(seconds, rms, peak, active_seconds, active_ratio, sample_rate)


def should_skip_low_activity_audio(summary: AudioActivitySummary, config: dict[str, Any]) -> AudioGuardDecision:
    if not bool(config.get("low_activity_guard_enabled", True)):
        return AudioGuardDecision(False)
    if summary.seconds <= 0:
        return AudioGuardDecision(True, "empty audio")

    peak_threshold = float(config.get("low_activity_peak_threshold", 0.008))
    rms_threshold = float(config.get("low_activity_rms_threshold", 0.0015))
    min_active_seconds = float(config.get("low_activity_min_active_seconds", 0.12))
    min_record_seconds = float(config.get("low_activity_min_record_seconds", 0.20))

    if summary.seconds < min_record_seconds and summary.active_seconds < min_active_seconds:
        return AudioGuardDecision(
            True,
            f"too short seconds={summary.seconds:.2f} active={summary.active_seconds:.2f}",
        )
    if summary.peak < peak_threshold and summary.rms < rms_threshold:
        return AudioGuardDecision(
            True,
            f"too quiet rms={summary.rms:.4f} peak={summary.peak:.4f}",
        )
    if summary.seconds >= 0.5 and summary.active_seconds < min_active_seconds and summary.peak < peak_threshold * 2.5:
        return AudioGuardDecision(
            True,
            f"low activity active={summary.active_seconds:.2f} peak={summary.peak:.4f}",
        )
    return AudioGuardDecision(False)
