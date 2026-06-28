from __future__ import annotations

import datetime as _datetime
import json
import msvcrt
import os
import queue
import tempfile
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any

from .clipboard import clear_alt_menu_focus
from .clipboard import copy_text
from .clipboard import get_caret_screen_rect
from .clipboard import get_focus_window
from .clipboard import get_foreground_window
from .clipboard import paste_text
from .clipboard import restore_focus
from .config import app_data_dir
from .config import default_config_path
from .config import load_config
from .config import save_config
from .config import WHISPER_MODEL_OPTIONS
from .config import POSTPROCESS_MODE_OPTIONS
from .config import WHISPER_BEAM_SIZE_OPTIONS
from .dictionary import VoiceDictionary
from .gemini_transcriber import GeminiAudioTranscriber
from .gemini_transcriber import get_api_key
from .gemini_transcriber import set_user_api_key
from .postprocess import postprocess
from .recorder import Recorder
from .streaming_prefetch import StreamingPrefetchSession
from .transcriber import FasterWhisperTranscriber
from .whisper_hints import build_whisper_hints


class AppState(str, Enum):
    READY = "ready"
    STARTING = "starting"
    RECORDING = "recording"
    STOPPING = "stopping"
    PROCESSING = "processing"
    STOPPED = "stopped"
    ERROR = "error"


class _ListenerGroup:
    def __init__(self, listeners: list[Any]):
        self.listeners = listeners

    def stop(self) -> None:
        for listener in self.listeners:
            try:
                listener.stop()
            except Exception:
                pass


class WindowsVoiceTyperApp:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.dictionary = VoiceDictionary(str(config["dictionary_path"]))
        self.dictionary.ensure()
        self.recorder = Recorder(
            sample_rate=int(config.get("sample_rate", 16000)),
            device=config.get("input_device", "auto"),
        )
        self.transcriber = self._make_transcriber()
        self._lock = threading.Lock()
        self._busy = False
        self._created_at = time.perf_counter()
        self._state = AppState.READY
        self._state_started_at = time.perf_counter()
        self._model_loading = False
        self._stop_event = threading.Event()
        self._keyboard_listener = None
        self._mouse_listener = None
        self._tray_icon = None
        self._lock_file_handle = None
        self._recording_timer = None
        self._control_root = None
        self._control_status_var = None
        self._hud_mode_var = None
        self._level_bar = None
        self._progress_bar = None
        self._paste_target_hwnd = 0
        self._paste_target_focus_hwnd = 0
        self._last_activation_source = ""
        self._last_activation_needs_alt_cleanup = False
        self._model_warmup_thread = None
        self._model_setup_thread = None
        self._streaming_session = None
        self._status_queue: queue.Queue[str] = queue.Queue()
        self.log_path = app_data_dir() / "koe-kichi.log"
        self.history_path = app_data_dir() / "history.json"
        self._history_lock = threading.Lock()
        self._whisper_hints_lock = threading.Lock()
        self._whisper_hints_cache_key = None
        self._whisper_hints_cache = None

    def _make_transcriber(self) -> FasterWhisperTranscriber:
        return FasterWhisperTranscriber(
            model=str(self.config.get("whisper_model", "small")),
            device=str(self.config.get("whisper_device", "cpu")),
            compute_type=str(self.config.get("whisper_compute_type", "int8")),
            language=str(self.config.get("language", "ja")),
            cpu_fallback=bool(self.config.get("whisper_cpu_fallback", True)),
            cpu_threads=self.config.get("whisper_cpu_threads", "auto"),
            num_workers=int(self.config.get("whisper_num_workers", 1) or 1),
            beam_size=int(self.config.get("whisper_beam_size", 3) or 3),
            condition_on_previous_text=bool(self.config.get("whisper_condition_on_previous_text", False)),
        )

    def _whisper_hints(self) -> Any:
        key = self._whisper_hints_cache_token()
        with self._whisper_hints_lock:
            if self._whisper_hints_cache_key == key and self._whisper_hints_cache is not None:
                return self._whisper_hints_cache
            hints = build_whisper_hints(self.config, self.dictionary)
            self._whisper_hints_cache_key = key
            self._whisper_hints_cache = hints
            return hints

    def _whisper_hints_cache_token(self) -> tuple[Any, ...]:
        dictionary_token = None
        try:
            stat = self.dictionary.path.stat()
            dictionary_token = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
        return (
            dictionary_token,
            str(self.config.get("whisper_prompt", "")),
            bool(self.config.get("whisper_auto_prompt_hints_enabled", True)),
            bool(self.config.get("whisper_hotwords_enabled", False)),
            str(self.config.get("whisper_hint_max_terms", 40)),
            str(self.config.get("whisper_hotwords_max_terms", 20)),
        )

    def _invalidate_whisper_hints(self) -> None:
        with self._whisper_hints_lock:
            self._whisper_hints_cache_key = None
            self._whisper_hints_cache = None

    def _transcription_provider(self) -> str:
        return str(self.config.get("transcription_provider", "local_whisper")).strip().lower()

    def _transition_locked(self, state: AppState, reason: str = "") -> None:
        previous = self._state
        if previous == state:
            return
        elapsed = time.perf_counter() - self._state_started_at
        self._state = state
        self._state_started_at = time.perf_counter()
        self._busy = state in (AppState.STARTING, AppState.STOPPING, AppState.PROCESSING)
        suffix = f" reason={reason}" if reason else ""
        self._log(f"state {previous.value} -> {state.value} after={elapsed:.2f}s{suffix}")

    def _current_state(self) -> AppState:
        with self._lock:
            return self._state

    def start_recording(self, target_hwnd: int | None = None, target_focus_hwnd: int | None = None) -> bool:
        with self._lock:
            if self._model_loading:
                self._log("recording start ignored: model setup is running")
                self._set_status("Model setup is running")
                return False
            if self._state != AppState.READY or self.recorder.is_recording:
                self._log(f"recording start ignored: state={self._state.value} recording={self.recorder.is_recording}")
                return False
            self._paste_target_hwnd = int(target_hwnd or get_foreground_window() or 0)
            self._paste_target_focus_hwnd = int(target_focus_hwnd or get_focus_window() or 0)
            self._transition_locked(AppState.STARTING, "start requested")
            self._log(f"paste target hwnd: {self._paste_target_hwnd} focus: {self._paste_target_focus_hwnd}")
        if self._paste_target_hwnd:
            restored = self._restore_activation_focus("start")
            self._log(f"focus restore after start request: {restored}")
        try:
            self.recorder.start()
        except Exception as error:
            with self._lock:
                self._transition_locked(AppState.READY, "recording start failed")
                self._log(f"recording start failed: {error}")
            self._set_status("Error: could not open microphone")
            self._notify("Koe Kichi error", str(error)[:120])
            return False
        self._schedule_recording_timeout()
        self._start_streaming_prefetch()
        with self._lock:
            self._transition_locked(AppState.RECORDING, "recording started")
            self._log(f"recording started: {self.recorder.input_device_name}")
        self._set_status("Recording - double-tap Alt to stop")
        return True

    def stop_recording(self) -> bool:
        with self._lock:
            if self._state in (AppState.STOPPING, AppState.PROCESSING):
                self._log(f"recording stop ignored: state={self._state.value}")
                return False
            if not self.recorder.is_recording:
                self._log(f"recording stop ignored: state={self._state.value} recorder is not running")
                self._transition_locked(AppState.READY, "stop ignored")
                self._set_status("Ready - double-tap Alt to start")
                return False
            self._transition_locked(AppState.STOPPING, "stop requested")
            self._cancel_recording_timeout()
        try:
            audio_path = self.recorder.stop_to_wav()
        except Exception as error:
            self._stop_streaming_prefetch()
            with self._lock:
                self._transition_locked(AppState.READY, "recording stop failed")
                self._log(f"recording stop failed: {error}")
            self._set_status("Ready - double-tap Alt to start")
            return False
        with self._lock:
            streaming_session = self._streaming_session
            self._streaming_session = None
            self._transition_locked(AppState.PROCESSING, "audio captured")
        self._log(f"recording stopped: {audio_path}")
        if self._paste_target_hwnd:
            restored = self._restore_activation_focus("stop")
            self._log(f"focus restore after stop request: {restored}")
        self._set_status("Transcribing...")
        threading.Thread(target=self._transcribe_and_paste, args=(audio_path, streaming_session), daemon=True).start()
        return True

    def toggle_recording(self, target_hwnd: int | None = None, target_focus_hwnd: int | None = None) -> None:
        state = self._current_state()
        if self.recorder.is_recording or state == AppState.RECORDING:
            self.stop_recording()
        elif state == AppState.READY:
            self.start_recording(target_hwnd=target_hwnd, target_focus_hwnd=target_focus_hwnd)
        else:
            self._log(f"recording toggle ignored: state={state.value}")

    def _restore_activation_focus(self, phase: str) -> bool:
        if (
            bool(self.config.get("alt_menu_escape_after_double_tap", True))
            and self._last_activation_needs_alt_cleanup
        ):
            cleared = clear_alt_menu_focus(self._paste_target_hwnd, self._paste_target_focus_hwnd)
            self._log(f"alt menu focus clear after {phase}: {cleared}")
            self._last_activation_needs_alt_cleanup = False
            return cleared
        return restore_focus(self._paste_target_hwnd, self._paste_target_focus_hwnd)

    def _set_activation_source(self, source: str, *, needs_alt_cleanup: bool = False) -> None:
        self._last_activation_source = source
        self._last_activation_needs_alt_cleanup = bool(needs_alt_cleanup)

    def run_forever(self) -> None:
        if not self._acquire_single_instance_lock():
            self._log("another Koe Kichi instance is already running")
            return

        self._start_keyboard_listener()
        self._start_mouse_listener()
        self._start_tray_icon()
        self._start_model_warmup()
        self._log(f"startup initialized seconds={time.perf_counter() - self._created_at:.2f}")
        self._log("koe-kichi is running. Double-tap Alt to start/stop recording.")
        try:
            if not self._run_control_window():
                while not self._stop_event.wait(1.0):
                    pass
        except KeyboardInterrupt:
            self.stop()
        finally:
            self.stop()
            self._log("stopped")

    def _start_streaming_prefetch(self) -> None:
        self._streaming_session = None
        if self._transcription_provider() == "gemini_audio":
            return
        if not bool(self.config.get("streaming_prefetch_enabled", True)):
            return
        try:
            hints = self._whisper_hints()
            session = StreamingPrefetchSession(
                recorder=self.recorder,
                transcriber=self.transcriber,
                config=self.config,
                log=self._log,
                whisper_prompt=hints.prompt,
                whisper_hotwords=hints.hotwords,
            )
            session.start()
            self._streaming_session = session
        except Exception as error:
            self._streaming_session = None
            self._log(f"streaming prefetch unavailable: {error}")

    def _stop_streaming_prefetch(self) -> None:
        session = self._streaming_session
        self._streaming_session = None
        if session is None:
            return
        try:
            session.cancel()
        except Exception as error:
            self._log(f"streaming prefetch cleanup failed: {error}")

    def _start_model_warmup(self) -> None:
        if not bool(self.config.get("preload_model_at_startup", False)):
            self._set_status("Ready - double-tap Alt to start")
            self._log("whisper model preload disabled")
            return
        if self._transcription_provider() == "gemini_audio" and not bool(self.config.get("gemini_preload_local_fallback", False)):
            self._set_status("Ready - double-tap Alt to start")
            self._log("whisper model warmup skipped: transcription_provider=gemini_audio")
            return
        if self._model_warmup_thread is not None:
            return

        def warmup() -> None:
            started = time.perf_counter()
            model = str(self.config.get("whisper_model", "small"))
            device = str(self.config.get("whisper_device", "cpu"))
            compute_type = str(self.config.get("whisper_compute_type", "int8"))
            self._model_loading = True
            self._set_status(f"Loading Whisper model: {model}")
            self._log(
                "whisper model warmup started: "
                f"model={model} device={device} compute_type={compute_type} "
                f"cpu_threads={self.transcriber.cpu_threads} num_workers={self.transcriber.num_workers}"
            )
            try:
                self.transcriber.ensure_model()
            except Exception as error:
                self._log(f"whisper model warmup failed: {error}")
                self._set_status("Model load failed - see log")
                self._notify("Koe Kichi model error", str(error)[:120])
                return
            finally:
                self._model_loading = False
            self._log(f"whisper model warmup complete seconds={time.perf_counter() - started:.2f}")
            with self._lock:
                ready_for_status = self._state == AppState.READY
            if not self.recorder.is_recording and ready_for_status:
                self._set_status("Ready - double-tap Alt to start")

        self._model_warmup_thread = threading.Thread(target=warmup, daemon=True)
        self._model_warmup_thread.start()

    def _run_model_setup(self, *, allow_while_busy: bool = False, notify_when_already_running: bool = True) -> None:
        with self._lock:
            running = self._model_setup_thread is not None and self._model_setup_thread.is_alive()
            if running or self._model_loading:
                self._log("model setup request ignored: already running")
                if notify_when_already_running:
                    self._notify("Koe Kichi setup", "Whisper model setup is already running.")
                return
            if not allow_while_busy and (self.recorder.is_recording or self._busy):
                self._log("model setup request ignored: app is recording or processing")
                self._notify("Koe Kichi setup", "録音中または処理中はセットアップを開始できません。")
                return

        def setup() -> None:
            started = time.perf_counter()
            model = str(self.config.get("whisper_model", "small") or "small")
            device = str(self.config.get("whisper_device", "cpu") or "cpu")
            compute_type = str(self.config.get("whisper_compute_type", "int8") or "int8")
            self._model_loading = True
            self._set_status(f"Setting up Whisper model: {model}")
            self._log(
                "whisper model setup started: "
                f"model={model} device={device} compute_type={compute_type} "
                f"cpu_threads={self.transcriber.cpu_threads} num_workers={self.transcriber.num_workers}"
            )
            try:
                self.transcriber.ensure_model()
            except Exception as error:
                self._log(f"whisper model setup failed: {error}")
                self._set_status("Model setup failed - see log")
                self._notify("Koe Kichi setup failed", "モデルを準備できませんでした。ネットワークとモデル名を確認してください。")
                return
            finally:
                self._model_loading = False
                self._model_setup_thread = None
            self._log(f"whisper model setup complete seconds={time.perf_counter() - started:.2f}")
            with self._lock:
                ready_for_status = self._state == AppState.READY
            if not self.recorder.is_recording and ready_for_status:
                self._set_status("Ready - model is ready")
            self._notify("Koe Kichi setup complete", f"Whisper model is ready: {model}")

        thread = threading.Thread(target=setup, daemon=True)
        self._model_setup_thread = thread
        thread.start()

    def _is_model_setup_error(self, error: Exception) -> bool:
        message = str(error).lower()
        needles = (
            "faster-whisper",
            "whispermodel",
            "model",
            "huggingface",
            "local cache",
            "network",
            "download",
        )
        return any(needle in message for needle in needles)

    def stop(self) -> None:
        with self._lock:
            self._transition_locked(AppState.STOPPED, "app stopping")
        self._stop_event.set()
        self._cancel_recording_timeout()
        self._stop_streaming_prefetch()
        if self.recorder.is_recording:
            try:
                self.recorder.stop_to_wav().unlink(missing_ok=True)
            except Exception as error:
                self._log(f"recording cleanup failed: {error}")
        if self._keyboard_listener is not None:
            try:
                self._keyboard_listener.stop()
            except Exception as error:
                self._log(f"keyboard listener stop failed: {error}")
            self._keyboard_listener = None
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception as error:
                self._log(f"middle-click listener stop failed: {error}")
            self._mouse_listener = None
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception as error:
                self._log(f"tray icon stop failed: {error}")
            self._tray_icon = None
        root = self._control_root
        if root is not None:
            try:
                root.after(0, root.destroy)
            except Exception:
                pass
        self._release_single_instance_lock()

    def _transcribe_and_paste(self, audio_path: Path, streaming_session: Any | None = None) -> None:
        timings: dict[str, float] = {}
        workflow_started = time.perf_counter()
        run_setup_after_failure = False

        def timed(name: str, callback: Any) -> Any:
            started = time.perf_counter()
            try:
                return callback()
            finally:
                timings[name] = time.perf_counter() - started

        try:
            hints = self._whisper_hints()
            mode = "full"
            raw = ""
            provider = self._transcription_provider()
            if provider == "gemini_audio":
                if streaming_session is not None:
                    streaming_session.cancel()
                try:
                    raw = timed("gemini_transcribe", lambda: GeminiAudioTranscriber.from_config(self.config).transcribe(audio_path))
                    mode = "gemini_audio"
                    if not raw:
                        self._log("gemini transcription fallback: empty result")
                except Exception as error:
                    if not bool(self.config.get("gemini_fallback_to_local", True)):
                        raise
                    self._log(f"gemini transcription fallback: {error}")
                    raw = ""
                    mode = "full_after_gemini_fallback"
            elif provider not in ("", "local", "local_whisper", "whisper"):
                self._log(f"unknown transcription_provider={provider}; using local_whisper")
            if not raw and provider != "gemini_audio" and streaming_session is not None:
                try:
                    raw = timed("streaming_prefetch_finish", streaming_session.finish)
                    if raw:
                        mode = "streaming_prefetch"
                    else:
                        self._log("streaming prefetch fallback: empty result")
                except Exception as error:
                    self._log(f"streaming prefetch fallback: {error}")
                    raw = ""
            if not raw:
                raw = timed(
                    "local_transcribe",
                    lambda: self.transcriber.transcribe(audio_path, prompt=hints.prompt, hotwords=hints.hotwords),
                )
            timings["transcription_total"] = sum(
                timings.get(name, 0.0)
                for name in ("gemini_transcribe", "streaming_prefetch_finish", "local_transcribe")
            )
            self._log(f"transcription mode: {mode} seconds={timings['transcription_total']:.2f}")
            processed = timed("dictionary", lambda: self.dictionary.process(raw))
            result = timed("postprocess", lambda: postprocess(processed, self.config))
            output = result.text
            self._log(f"raw: {raw}")
            self._log(f"out: {output}")
            if output:
                timed("history", lambda: self._append_history(raw, output))
            if result.error:
                self._log(f"postprocess fallback: {result.error}")
            if not output:
                self._set_status("Ready - no speech recognized")
                self._notify("No text", "No speech was recognized.")
                return
            if bool(self.config.get("copy_output_to_clipboard", True)):
                try:
                    timed("copy", lambda: copy_text(output))
                except Exception as error:
                    self._log(f"clipboard copy failed: {error}")
            if bool(self.config.get("paste_after_transcription", True)):
                try:
                    timed(
                        "paste",
                        lambda: paste_text(
                            output,
                            preserve_clipboard=bool(self.config.get("preserve_clipboard", True))
                            and not bool(self.config.get("copy_output_to_clipboard", True)),
                            restore_delay=float(self.config.get("restore_clipboard_delay_seconds", 0.25)),
                            target_hwnd=self._paste_target_hwnd,
                            target_focus_hwnd=self._paste_target_focus_hwnd,
                        ),
                    )
                except Exception as error:
                    self._log(f"clipboard paste failed: {error}")
                    self._set_status("Ready - paste failed")
                    self._notify("Koe Kichi paste error", str(error)[:120])
                    return
            self._set_status("Ready - pasted")
        except Exception as error:
            self._log(f"transcription failed: {error}")
            if self._is_model_setup_error(error):
                run_setup_after_failure = True
                self._set_status("Model not ready - starting setup")
                self._notify("Koe Kichi setup", "モデル未準備の可能性があります。セットアップを開始します。")
            else:
                self._set_status("Error - see log")
                self._notify("Koe Kichi error", str(error)[:120])
            with self._lock:
                self._transition_locked(AppState.ERROR, "processing failed")
        finally:
            try:
                audio_path.unlink(missing_ok=True)
            except Exception:
                pass
            timings["workflow_total"] = time.perf_counter() - workflow_started
            if timings:
                self._log(
                    "workflow timings: "
                    + " ".join(f"{name}={seconds:.2f}s" for name, seconds in sorted(timings.items()))
                )
            with self._lock:
                if self._state != AppState.STOPPED:
                    self._transition_locked(AppState.READY, "processing finished")
            if run_setup_after_failure:
                self._run_model_setup(allow_while_busy=True, notify_when_already_running=False)

    def _start_keyboard_listener(self) -> None:
        listeners: list[Any] = []
        record_key = str(self.config.get("record_key", "alt")).lower()
        double_tap_interval = float(self.config.get("double_tap_interval_seconds", 0.45))
        if bool(self.config.get("double_tap_to_toggle", True)):
            listener = self._create_double_tap_listener(record_key, double_tap_interval)
            if listener is not None:
                listeners.append(listener)

        if bool(self.config.get("hold_to_record", False)):
            hold_key = str(self.config.get("hold_record_key", "f8") or "f8").strip().lower()
            listener = self._create_hold_keyboard_listener(
                hold_key,
                float(self.config.get("hold_start_delay_seconds", 0.2)),
            )
            if listener is not None:
                listeners.append(listener)

        if not listeners:
            self._log("keyboard listener disabled")
        elif len(listeners) == 1:
            self._keyboard_listener = listeners[0]
        else:
            self._keyboard_listener = _ListenerGroup(listeners)

    def _create_double_tap_listener(self, record_key: str, double_tap_interval: float) -> Any | None:
        backend = str(self.config.get("input_listener_backend", "polling")).strip().lower()
        if backend != "low_level":
            from .polling_input import PollingDoubleTapListener

            def get_target() -> tuple[int, int]:
                if self.recorder.is_recording or self._busy:
                    return 0, 0
                return get_foreground_window(), get_focus_window()

            def on_double_tap(target_hwnd: int = 0, target_focus_hwnd: int = 0) -> None:
                self._log(f"{record_key} double tap detected")
                self._set_activation_source(
                    record_key,
                    needs_alt_cleanup=record_key in ("alt", "option"),
                )
                self.toggle_recording(target_hwnd=target_hwnd, target_focus_hwnd=target_focus_hwnd)

            listener = PollingDoubleTapListener(
                key=record_key,
                interval_seconds=double_tap_interval,
                callback=on_double_tap,
                get_target=get_target,
            )
            listener.start()
            self._log(f"keyboard listener started: record_key={record_key}, mode=polling_double_tap")
            return listener

        if record_key not in ("alt", "option"):
            return self._create_pynput_double_tap_listener(record_key, double_tap_interval)
        from .keyboard_hook import AltDoubleTapHook

        def get_target() -> tuple[int, int]:
            if self.recorder.is_recording or self._busy:
                return 0, 0
            return get_foreground_window(), get_focus_window()

        def on_double_tap(target_hwnd: int, target_focus_hwnd: int) -> None:
            self._log(f"{record_key} double tap detected")
            self._set_activation_source(record_key)
            threading.Thread(
                target=self.toggle_recording,
                kwargs={
                    "target_hwnd": target_hwnd,
                    "target_focus_hwnd": target_focus_hwnd,
                },
                daemon=True,
            ).start()

        try:
            self._keyboard_listener = AltDoubleTapHook(
                interval_seconds=double_tap_interval,
                get_target=get_target,
                on_double_tap=on_double_tap,
            )
            self._keyboard_listener.start()
            self._log(f"keyboard listener started: record_key={record_key}, mode=double_tap_suppressed_async")
            return self._keyboard_listener
        except Exception as error:
            self._log(f"keyboard hook failed; falling back to pynput: {error}")
            return self._create_pynput_double_tap_listener(record_key, double_tap_interval)

    def _create_pynput_double_tap_listener(self, record_key: str, double_tap_interval: float) -> Any | None:
        from pynput import keyboard

        state: dict[str, Any] = {
            "key_down": False,
            "last_tap_at": 0.0,
        }
        lock = threading.Lock()

        def on_press(key: Any) -> None:
            if not _matches_key(key, record_key, keyboard):
                return
            now = time.monotonic()
            with lock:
                if bool(state["key_down"]):
                    return
                state["key_down"] = True

        def on_release(key: Any) -> None:
            if not _matches_key(key, record_key, keyboard):
                return
            now = time.monotonic()
            should_toggle = False
            with lock:
                state["key_down"] = False
                last_tap_at = float(state.get("last_tap_at", 0.0) or 0.0)
                if last_tap_at and now - last_tap_at <= double_tap_interval:
                    state["last_tap_at"] = 0.0
                    should_toggle = True
                else:
                    state["last_tap_at"] = now
            if should_toggle:
                self._log(f"{record_key} double tap detected")
                self._set_activation_source(
                    record_key,
                    needs_alt_cleanup=record_key in ("alt", "option"),
                )
                threading.Thread(target=self.toggle_recording, daemon=True).start()

        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.start()
        self._log(f"keyboard listener started: record_key={record_key}, mode=double_tap")
        return listener

    def _create_hold_keyboard_listener(self, hold_key: str, start_delay: float) -> Any | None:
        if not hold_key:
            return None
        from .polling_input import PollingHoldListener

        def on_start() -> None:
            self._log(f"{hold_key} hold recording start")
            self._set_activation_source(hold_key)
            self.start_recording()

        def on_stop() -> None:
            self._log(f"{hold_key} hold recording stop")
            self.stop_recording()

        listener = PollingHoldListener(
            key=hold_key,
            start_delay_seconds=start_delay,
            on_start=on_start,
            on_stop=on_stop,
        )
        listener.start()
        self._log(f"keyboard listener started: hold_record_key={hold_key}, mode=polling_hold_to_record")
        return listener

    def _start_mouse_listener(self) -> None:
        if not bool(self.config.get("middle_click_toggle_recording", False)):
            self._log("middle-click listener disabled")
            return
        try:
            from .polling_input import PollingClickListener

            def on_middle_click() -> None:
                self._log("middle click detected")
                self._set_activation_source("middle_mouse")
                self.toggle_recording()

            self._mouse_listener = PollingClickListener(
                key="middle_mouse",
                callback=on_middle_click,
                debounce_seconds=float(self.config.get("middle_click_debounce_seconds", 0.45)),
            )
            self._mouse_listener.start()
            if bool(self.config.get("middle_click_suppress_native", False)):
                self._log("middle-click native suppression ignored in polling mode")
            self._log("middle-click listener started: mode=polling")
        except Exception as error:
            self._mouse_listener = None
            self._log(f"middle-click hook unavailable: {error}")

    def _run_control_window(self) -> bool:
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as error:
            self._log(f"control window unavailable: {error}")
            return False

        root = tk.Tk()
        root.withdraw()
        self._control_root = root

        hud = tk.Toplevel(root)
        hud.withdraw()
        hud.title("Koe Kichi")
        hud.geometry("150x34+40+40")
        hud.resizable(False, False)
        hud.configure(bg="#272c33")
        try:
            hud.attributes("-topmost", bool(self.config.get("hud_topmost", True)))
        except Exception:
            pass
        try:
            hud.attributes("-alpha", 0.88)
        except Exception:
            pass
        try:
            hud.overrideredirect(True)
        except Exception:
            pass
        hud.protocol("WM_DELETE_WINDOW", self.stop)

        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(
            "Koe.Horizontal.TProgressbar",
            troughcolor="#3e4650",
            background="#6aa6ff",
            bordercolor="#272c33",
            lightcolor="#6aa6ff",
            darkcolor="#6aa6ff",
            thickness=8,
        )

        state_var = tk.StringVar(value="\u5f85\u6a5f")
        self._hud_mode_var = state_var
        self._control_status_var = None

        frame = tk.Frame(hud, bg="#272c33", padx=8, pady=6)
        frame.pack(fill=tk.BOTH, expand=True)

        state_label = tk.Label(
            frame,
            textvariable=state_var,
            width=4,
            anchor="w",
            bg="#272c33",
            fg="#f1f3f4",
            font=("Segoe UI", 9, "bold"),
        )
        state_label.pack(side=tk.LEFT, padx=(0, 6))

        self._level_bar = ttk.Progressbar(
            frame,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            length=84,
            style="Koe.Horizontal.TProgressbar",
        )
        self._progress_bar = ttk.Progressbar(
            frame,
            orient="horizontal",
            mode="indeterminate",
            length=84,
            style="Koe.Horizontal.TProgressbar",
        )

        menu = tk.Menu(hud, tearoff=0)
        menu.add_command(label="\u8a2d\u5b9a...", command=self._open_settings_window)
        menu.add_separator()
        menu.add_command(label="\u7d42\u4e86", command=self.stop)

        def show_menu(event: Any) -> None:
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        drag = {"x": 0, "y": 0}

        def start_drag(event: Any) -> None:
            drag["x"] = event.x
            drag["y"] = event.y

        def drag_to(event: Any) -> None:
            x = event.x_root - int(drag["x"])
            y = event.y_root - int(drag["y"])
            show_no_activate(150, 34, x, y)

        for widget in (hud, frame, state_label, self._level_bar, self._progress_bar):
            widget.bind("<Button-3>", show_menu)
            widget.bind("<Button-1>", start_drag)
            widget.bind("<B1-Motion>", drag_to)

        progress_running = {"value": False}
        current_view = {"value": ""}
        hud_visible = {"value": False}
        hud_hwnd = {"value": 0}

        GA_ROOT = 2
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_TOPMOST = 0x00000008
        WS_EX_NOACTIVATE = 0x08000000
        HWND_TOPMOST = -1
        SW_SHOWNOACTIVATE = 4
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        ROUND_RADIUS = 12

        def apply_rounded_region(hwnd: int, width: int, height: int) -> None:
            try:
                import ctypes

                gdi32 = ctypes.windll.gdi32
                user32 = ctypes.windll.user32
                region = gdi32.CreateRoundRectRgn(0, 0, int(width) + 1, int(height) + 1, ROUND_RADIUS, ROUND_RADIUS)
                if region:
                    result = user32.SetWindowRgn(hwnd, region, True)
                    if not result:
                        gdi32.DeleteObject(region)
            except Exception as error:
                self._log(f"hud rounded region failed: {error}")
        def configure_no_activate() -> int:
            try:
                import ctypes

                user32 = ctypes.windll.user32
                base_hwnd = int(hud.winfo_id())
                hwnd = int(hud_hwnd["value"] or user32.GetAncestor(base_hwnd, GA_ROOT) or base_hwnd)
                get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
                set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
                style_value = int(get_style(hwnd, GWL_EXSTYLE))
                style_value |= WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE
                set_style(hwnd, GWL_EXSTYLE, style_value)
                hud_hwnd["value"] = hwnd
                return hwnd
            except Exception as error:
                self._log(f"hud no-activate style failed: {error}")
                return 0

        def show_no_activate(width: int, height: int, x: int, y: int) -> None:
            try:
                import ctypes

                user32 = ctypes.windll.user32
                active_before = int(user32.GetForegroundWindow() or 0)
                hud.geometry(f"{width}x{height}+{x}+{y}")
                hud.update_idletasks()
                hwnd = configure_no_activate()
                if not hwnd:
                    raise RuntimeError("HUD hwnd is unavailable")
                apply_rounded_region(hwnd, width, height)
                hud.deiconify()
                hud.update_idletasks()
                user32.SetWindowPos(
                    hwnd,
                    HWND_TOPMOST,
                    int(x),
                    int(y),
                    int(width),
                    int(height),
                    SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
                user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                if active_before and int(user32.GetForegroundWindow() or 0) != active_before:
                    user32.SetForegroundWindow(active_before)
            except Exception as error:
                self._log(f"hud no-activate show failed: {error}")
                hud.geometry(f"{width}x{height}+{x}+{y}")
                hud.deiconify()

        def hide_no_activate() -> None:
            try:
                hud.withdraw()
            except Exception:
                pass

        root.update_idletasks()
        hud.update_idletasks()
        configure_no_activate()
        hide_no_activate()

        def set_progress_running(running: bool) -> None:
            if self._progress_bar is None:
                return
            if running and not progress_running["value"]:
                self._progress_bar.start(12)
                progress_running["value"] = True
            elif not running and progress_running["value"]:
                self._progress_bar.stop()
                self._progress_bar["value"] = 0
                progress_running["value"] = False

        def place_near_pointer(width: int, height: int) -> tuple[int, int]:
            try:
                pointer_x = root.winfo_pointerx()
                pointer_y = root.winfo_pointery()
                screen_w = root.winfo_screenwidth()
                screen_h = root.winfo_screenheight()
            except Exception:
                pointer_x = 40
                pointer_y = 40
                screen_w = 1920
                screen_h = 1080
            x = max(8, min(pointer_x + 14, screen_w - width - 8))
            y = max(8, min(pointer_y + 18, screen_h - height - 8))
            return x, y

        def clamp_to_screen(x: int, y: int, width: int, height: int) -> tuple[int, int]:
            try:
                screen_w = root.winfo_screenwidth()
                screen_h = root.winfo_screenheight()
            except Exception:
                screen_w = 1920
                screen_h = 1080
            return (
                max(8, min(int(x), screen_w - width - 8)),
                max(8, min(int(y), screen_h - height - 8)),
            )

        def fits_screen(x: int, y: int, width: int, height: int) -> bool:
            try:
                screen_w = root.winfo_screenwidth()
                screen_h = root.winfo_screenheight()
            except Exception:
                screen_w = 1920
                screen_h = 1080
            return 8 <= x <= screen_w - width - 8 and 8 <= y <= screen_h - height - 8

        def place_near_text_target(width: int, height: int) -> tuple[int, int]:
            caret = get_caret_screen_rect(self._paste_target_focus_hwnd or self._paste_target_hwnd or None)
            if caret is None:
                return place_near_pointer(width, height)
            left, top, right, bottom = caret
            gap_x = 18
            gap_y = 10
            candidates = [
                (right + gap_x, bottom + gap_y),
                (left - width - gap_x, bottom + gap_y),
                (right + gap_x, top - height - gap_y),
                (left - width - gap_x, top - height - gap_y),
                (right + gap_x, max(8, top - 6)),
                (left - width - gap_x, max(8, top - 6)),
            ]
            for x, y in candidates:
                if fits_screen(int(x), int(y), width, height):
                    return int(x), int(y)
            return clamp_to_screen(right + gap_x, bottom + gap_y, width, height)

        def show_window(width: int, height: int) -> None:
            if not hud_visible["value"]:
                x, y = place_near_text_target(width, height)
                show_no_activate(width, height, x, y)
                hud_visible["value"] = True
                return
            show_no_activate(width, height, hud.winfo_x(), hud.winfo_y())

        def hide_window() -> None:
            if not hud_visible["value"]:
                return
            set_progress_running(False)
            hide_no_activate()
            hud_visible["value"] = False

        def switch_view(view: str) -> None:
            if view == current_view["value"]:
                return
            current_view["value"] = view
            if self._level_bar is not None:
                self._level_bar.pack_forget()
            if self._progress_bar is not None:
                self._progress_bar.pack_forget()
            if view == "recording":
                state_var.set("\u9332\u97f3")
                if self._level_bar is not None:
                    self._level_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
                show_window(150, 34)
                set_progress_running(False)
            elif view == "loading":
                state_var.set("\u8aad\u8fbc")
                if self._progress_bar is not None:
                    self._progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
                show_window(150, 34)
                set_progress_running(True)
            elif view == "working":
                state_var.set("\u51e6\u7406")
                if self._progress_bar is not None:
                    self._progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
                show_window(150, 34)
                set_progress_running(True)
            else:
                state_var.set("\u5f85\u6a5f")
                hide_window()

        def poll_status() -> None:
            try:
                while True:
                    self._status_queue.get_nowait()
            except queue.Empty:
                pass

            if self._level_bar is not None:
                self._level_bar["value"] = self.recorder.level_percent

            if self.recorder.is_recording:
                switch_view("recording")
            elif self._busy:
                switch_view("working")
            elif self._model_loading:
                switch_view("loading")
            else:
                switch_view("idle")

            if self._stop_event.is_set():
                try:
                    root.destroy()
                except Exception:
                    pass
                return
            root.after(100, poll_status)

        root.after(100, poll_status)
        root.mainloop()
        self._control_root = None
        return True
    def _schedule_ui(self, callback: Any) -> None:
        root = self._control_root
        if root is None:
            self._log("ui request ignored: control root is not ready")
            return
        try:
            root.after(0, callback)
        except Exception as error:
            self._log(f"ui request failed: {error}")

    def _append_history(self, raw: str, output: str) -> None:
        item = {
            "time": _datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "raw": raw,
            "out": output,
        }
        with self._history_lock:
            history = self._load_history_unlocked()
            history.insert(0, item)
            del history[int(self.config.get("history_limit", 200)) :]
            self._save_history_unlocked(history)

    def _load_history_unlocked(self) -> list[dict[str, Any]]:
        try:
            if not self.history_path.exists():
                return []
            with self.history_path.open("r", encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, list):
                return [item for item in loaded if isinstance(item, dict)]
        except Exception as error:
            self._log(f"history load failed: {error}")
            self._quarantine_bad_history()
        return []

    def _save_history_unlocked(self, history: list[dict[str, Any]]) -> None:
        tmp_name = ""
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{self.history_path.name}.",
                suffix=".tmp",
                dir=self.history_path.parent,
                text=True,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(history, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp_name, self.history_path)
            tmp_name = ""
        except Exception as error:
            self._log(f"history save failed: {error}")
        finally:
            if tmp_name and os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except Exception:
                    pass

    def _quarantine_bad_history(self) -> None:
        try:
            if not self.history_path.exists():
                return
            stamp = _datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            target = self.history_path.with_name(f"{self.history_path.name}.bad-{stamp}")
            self.history_path.replace(target)
            self._log(f"history moved aside: {target}")
        except Exception as error:
            self._log(f"history quarantine failed: {error}")

    def _open_settings_window(self) -> None:
        try:
            import tkinter as tk
            from tkinter import messagebox
            from tkinter import ttk
        except Exception as error:
            self._log(f"settings window unavailable: {error}")
            return

        root = self._control_root
        if root is None:
            return

        config_path = default_config_path()
        try:
            current = load_config(config_path)
        except Exception as error:
            self._log(f"settings load failed: {error}")
            current = dict(self.config)

        window = tk.Toplevel(root)
        window.title("Koe Kichi Settings")
        window.geometry("720x800+130+60")
        window.minsize(660, 740)

        main = ttk.Frame(window, padding=14)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(1, weight=1)

        device_options = _input_device_options()
        device_label_to_value = {label: value for value, label in device_options}
        device_value = str(current.get("input_device", "auto"))
        if not any(str(value) == device_value for value, _label in device_options):
            device_options.append((device_value, f"{device_value}: Current configured microphone"))
            device_label_to_value = {label: value for value, label in device_options}
        device_label = _label_for_value(device_options, device_value)
        device_var = tk.StringVar(value=device_label)

        key_options = [
            ("alt", "Alt double-tap"),
            ("ctrl", "Ctrl double-tap"),
            ("shift", "Shift double-tap"),
            ("f9", "F9 double-tap"),
        ]
        key_label_to_value = {label: value for value, label in key_options}
        key_var = tk.StringVar(value=_label_for_value(key_options, str(current.get("record_key", "alt")).lower()))
        hold_key_options = [
            ("f6", "F6"),
            ("f7", "F7"),
            ("f8", "F8"),
            ("f9", "F9"),
            ("f10", "F10"),
            ("f11", "F11"),
            ("f12", "F12"),
            ("ctrl", "Ctrl"),
            ("shift", "Shift"),
        ]
        hold_key_label_to_value = {label: value for value, label in hold_key_options}
        hold_enabled_var = tk.BooleanVar(value=bool(current.get("hold_to_record", False)))
        hold_key_var = tk.StringVar(
            value=_label_for_value(
                hold_key_options,
                str(current.get("hold_record_key", "f8") or "f8").lower(),
            )
        )
        middle_click_var = tk.BooleanVar(value=bool(current.get("middle_click_toggle_recording", False)))
        middle_click_suppress_var = tk.BooleanVar(value=bool(current.get("middle_click_suppress_native", False)))

        provider_options = [
            ("local_whisper", "Local Whisper"),
            ("gemini_audio", "Gemini API one-call audio"),
        ]
        provider_label_to_value = {label: value for value, label in provider_options}
        provider_var = tk.StringVar(
            value=_label_for_value(provider_options, str(current.get("transcription_provider", "local_whisper")).lower())
        )
        model_options = list(WHISPER_MODEL_OPTIONS)
        model_value = str(current.get("whisper_model", "small") or "small")
        if not any(value == model_value for value, _label in model_options):
            model_options.append((model_value, f"{model_value} - current custom model"))
        model_label_to_value = {label: value for value, label in model_options}
        model_var = tk.StringVar(value=_label_for_value(model_options, model_value))
        beam_options = list(WHISPER_BEAM_SIZE_OPTIONS)
        beam_value = int(current.get("whisper_beam_size", 3) or 3)
        if not any(value == beam_value for value, _label in beam_options):
            beam_options.append((beam_value, f"{beam_value} - current custom value"))
        beam_label_to_value = {label: value for value, label in beam_options}
        beam_var = tk.StringVar(value=_label_for_value(beam_options, beam_value))
        condition_previous_var = tk.BooleanVar(
            value=bool(current.get("whisper_condition_on_previous_text", False))
        )
        auto_prompt_hints_var = tk.BooleanVar(
            value=bool(current.get("whisper_auto_prompt_hints_enabled", True))
        )
        hotwords_enabled_var = tk.BooleanVar(
            value=bool(current.get("whisper_hotwords_enabled", False))
        )
        postprocess_options = list(POSTPROCESS_MODE_OPTIONS)
        postprocess_value = str(current.get("postprocess_mode", "local_punctuation") or "local_punctuation")
        if not any(value == postprocess_value for value, _label in postprocess_options):
            postprocess_options.append((postprocess_value, f"{postprocess_value} - current custom mode"))
        postprocess_label_to_value = {label: value for value, label in postprocess_options}
        postprocess_var = tk.StringVar(value=_label_for_value(postprocess_options, postprocess_value))
        ai_base_url_var = tk.StringVar(value=str(current.get("openai_compatible_base_url", "") or ""))
        ai_model_var = tk.StringVar(value=str(current.get("openai_compatible_model", "gpt-4.1-mini") or "gpt-4.1-mini"))
        ai_key_env_var = tk.StringVar(value=str(current.get("openai_compatible_api_key_env", "OPENAI_API_KEY") or "OPENAI_API_KEY"))
        gemini_env_var = tk.StringVar(value=str(current.get("gemini_api_key_env", "GEMINI_API_KEY") or "GEMINI_API_KEY"))
        API_KEY_MASK = "\u25cf" * 12
        gemini_key_var = tk.StringVar(value=API_KEY_MASK if get_api_key(gemini_env_var.get()) else "")
        gemini_key_state = {"dirty": False, "placeholder": bool(gemini_key_var.get())}
        preload_var = tk.BooleanVar(value=bool(current.get("preload_model_at_startup", False)))
        launch_var = tk.BooleanVar(value=bool(current.get("launch_at_login", False)))
        status_var = tk.StringVar(value="")
        api_status_var = tk.StringVar()

        def refresh_api_status(*_args: Any) -> None:
            env_name = gemini_env_var.get().strip() or "GEMINI_API_KEY"
            key_text = gemini_key_var.get()
            if gemini_key_state["dirty"] and key_text and key_text != API_KEY_MASK:
                api_status_var.set(f"APIキー: 貼り付け済み ({len(key_text)}文字)")
            else:
                api_status_var.set("APIキー: 設定済み" if get_api_key(env_name) else "APIキー: 未設定")

        def selected_provider() -> str:
            return provider_label_to_value.get(provider_var.get(), "local_whisper")

        def sync_gemini_state(*_args: Any) -> None:
            enabled = selected_provider() == "gemini_audio"
            state = "normal" if enabled else "disabled"
            gemini_env_entry.configure(state=state)
            gemini_key_entry.configure(state=state)
            paste_key_button.configure(state=state)
            refresh_api_status()

        def sync_hold_state(*_args: Any) -> None:
            hold_key_box.configure(state="normal" if hold_enabled_var.get() else "disabled")

        def sync_middle_click_state(*_args: Any) -> None:
            middle_click_suppress_check.configure(state="disabled")

        def selected_postprocess() -> str:
            return postprocess_label_to_value.get(postprocess_var.get(), "local_punctuation")

        def sync_postprocess_state(*_args: Any) -> None:
            enabled = selected_postprocess().startswith("openai_compatible_")
            state = "normal" if enabled else "disabled"
            ai_base_url_entry.configure(state=state)
            ai_model_entry.configure(state=state)
            ai_key_env_entry.configure(state=state)

        def mark_key_dirty(*_args: Any) -> None:
            if gemini_key_state["placeholder"] and gemini_key_var.get() == API_KEY_MASK:
                refresh_api_status()
                return
            gemini_key_state["dirty"] = True
            gemini_key_state["placeholder"] = False
            refresh_api_status()

        def clear_key_placeholder(_event: Any | None = None) -> None:
            if gemini_key_state["placeholder"] and gemini_key_var.get() == API_KEY_MASK:
                gemini_key_state["placeholder"] = False
                gemini_key_var.set("")
                gemini_key_state["dirty"] = False
                refresh_api_status()

        def paste_key_from_clipboard() -> None:
            try:
                key_text = root.clipboard_get().strip()
            except Exception:
                key_text = ""
            if not key_text:
                status_var.set("クリップボードにAPIキーがありません。")
                return
            gemini_key_state["placeholder"] = False
            gemini_key_state["dirty"] = True
            gemini_key_var.set(key_text)
            status_var.set("APIキーを貼り付けました。黒点で表示しています。")
            refresh_api_status()

        ttk.Label(main, text="Microphone").grid(row=0, column=0, sticky=tk.W, pady=6)
        device_box = ttk.Combobox(main, textvariable=device_var, values=[label for _value, label in device_options], state="readonly")
        device_box.grid(row=0, column=1, sticky=tk.EW, pady=6)

        ttk.Label(main, text="Activation key").grid(row=1, column=0, sticky=tk.W, pady=6)
        key_box = ttk.Combobox(main, textvariable=key_var, values=[label for _value, label in key_options], state="readonly")
        key_box.grid(row=1, column=1, sticky=tk.EW, pady=6)

        ttk.Label(main, text="Hold recording").grid(row=2, column=0, sticky=tk.W, pady=6)
        hold_row = ttk.Frame(main)
        hold_row.grid(row=2, column=1, sticky=tk.EW, pady=6)
        hold_row.columnconfigure(1, weight=1)
        ttk.Checkbutton(hold_row, text="Enable", variable=hold_enabled_var, command=sync_hold_state).grid(row=0, column=0, sticky=tk.W)
        hold_key_box = ttk.Combobox(
            hold_row,
            textvariable=hold_key_var,
            values=[label for _value, label in hold_key_options],
            state="normal",
        )
        hold_key_box.grid(row=0, column=1, sticky=tk.EW, padx=(8, 0))

        ttk.Label(main, text="Mouse third button").grid(row=3, column=0, sticky=tk.W, pady=6)
        middle_row = ttk.Frame(main)
        middle_row.grid(row=3, column=1, sticky=tk.EW, pady=6)
        ttk.Checkbutton(middle_row, text="Enable middle-click recording", variable=middle_click_var, command=sync_middle_click_state).grid(row=0, column=0, sticky=tk.W)
        middle_click_suppress_check = ttk.Checkbutton(
            middle_row,
            text="Native middle-click is not suppressed in safe mode",
            variable=middle_click_suppress_var,
        )
        middle_click_suppress_check.grid(row=1, column=0, sticky=tk.W, pady=(4, 0))

        ttk.Label(main, text="Transcription").grid(row=4, column=0, sticky=tk.W, pady=6)
        provider_box = ttk.Combobox(
            main,
            textvariable=provider_var,
            values=[label for _value, label in provider_options],
            state="readonly",
        )
        provider_box.grid(row=4, column=1, sticky=tk.EW, pady=6)

        ttk.Label(main, text="Whisper model").grid(row=5, column=0, sticky=tk.W, pady=6)
        model_box = ttk.Combobox(
            main,
            textvariable=model_var,
            values=[label for _value, label in model_options],
            state="readonly",
        )
        model_box.grid(row=5, column=1, sticky=tk.EW, pady=6)

        ttk.Label(main, text="Whisper accuracy").grid(row=6, column=0, sticky=tk.W, pady=6)
        beam_row = ttk.Frame(main)
        beam_row.grid(row=6, column=1, sticky=tk.EW, pady=6)
        beam_row.columnconfigure(0, weight=1)
        beam_box = ttk.Combobox(
            beam_row,
            textvariable=beam_var,
            values=[label for _value, label in beam_options],
            state="readonly",
        )
        beam_box.grid(row=0, column=0, sticky=tk.EW)
        ttk.Checkbutton(
            beam_row,
            text="Use previous text context",
            variable=condition_previous_var,
        ).grid(row=0, column=1, sticky=tk.W, padx=(10, 0))

        ttk.Label(main, text="Whisper hints").grid(row=7, column=0, sticky=tk.W, pady=6)
        hints_row = ttk.Frame(main)
        hints_row.grid(row=7, column=1, sticky=tk.EW, pady=6)
        ttk.Checkbutton(
            hints_row,
            text="Use auto prompt hints",
            variable=auto_prompt_hints_var,
        ).grid(row=0, column=0, sticky=tk.W)
        ttk.Checkbutton(
            hints_row,
            text="Use strong hotwords",
            variable=hotwords_enabled_var,
        ).grid(row=1, column=0, sticky=tk.W, pady=(4, 0))

        ttk.Label(main, text="Text correction").grid(row=8, column=0, sticky=tk.W, pady=6)
        postprocess_box = ttk.Combobox(
            main,
            textvariable=postprocess_var,
            values=[label for _value, label in postprocess_options],
            state="readonly",
        )
        postprocess_box.grid(row=8, column=1, sticky=tk.EW, pady=6)

        ttk.Label(main, text="AI correction URL").grid(row=9, column=0, sticky=tk.W, pady=6)
        ai_base_url_entry = ttk.Entry(main, textvariable=ai_base_url_var)
        ai_base_url_entry.grid(row=9, column=1, sticky=tk.EW, pady=6)

        ttk.Label(main, text="AI correction model").grid(row=10, column=0, sticky=tk.W, pady=6)
        ai_model_entry = ttk.Entry(main, textvariable=ai_model_var)
        ai_model_entry.grid(row=10, column=1, sticky=tk.EW, pady=6)

        ttk.Label(main, text="AI correction key env").grid(row=11, column=0, sticky=tk.W, pady=6)
        ai_key_env_entry = ttk.Entry(main, textvariable=ai_key_env_var)
        ai_key_env_entry.grid(row=11, column=1, sticky=tk.EW, pady=6)

        ttk.Label(main, text="Gemini API key env").grid(row=12, column=0, sticky=tk.W, pady=6)
        gemini_row = ttk.Frame(main)
        gemini_row.grid(row=12, column=1, sticky=tk.EW, pady=6)
        gemini_row.columnconfigure(0, weight=1)
        gemini_env_entry = ttk.Entry(gemini_row, textvariable=gemini_env_var)
        gemini_env_entry.grid(row=0, column=0, sticky=tk.EW)
        ttk.Label(gemini_row, textvariable=api_status_var).grid(row=0, column=1, padx=(10, 0))

        ttk.Label(main, text="Gemini API key").grid(row=13, column=0, sticky=tk.W, pady=6)
        key_row = ttk.Frame(main)
        key_row.grid(row=13, column=1, sticky=tk.EW, pady=6)
        key_row.columnconfigure(0, weight=1)
        gemini_key_entry = ttk.Entry(key_row, textvariable=gemini_key_var, show="\u25cf")
        gemini_key_entry.grid(row=0, column=0, sticky=tk.EW)
        paste_key_button = ttk.Button(key_row, text="貼り付け", command=paste_key_from_clipboard)
        paste_key_button.grid(row=0, column=1, padx=(8, 0))

        ttk.Checkbutton(main, text="Preload Whisper model at startup", variable=preload_var).grid(
            row=14,
            column=1,
            sticky=tk.W,
            pady=6,
        )
        ttk.Checkbutton(main, text="Launch Koe Kichi when I sign in", variable=launch_var).grid(
            row=15,
            column=1,
            sticky=tk.W,
            pady=6,
        )

        note = (
            "Local Whisper stays private and works offline after setup. "
            "Gemini sends each stopped recording to the Gemini API once."
        )
        ttk.Label(main, text=note, wraplength=660, foreground="#555555").grid(row=16, column=0, columnspan=2, sticky=tk.EW, pady=(12, 4))

        def save_settings() -> None:
            if self.recorder.is_recording or self._busy:
                messagebox.showinfo("Koe Kichi", "録音中または処理中は設定を保存できません。", parent=window)
                return
            try:
                config = load_config(config_path)
            except Exception:
                config = dict(self.config)

            before_device = str(self.config.get("input_device", "auto"))
            before_key = str(self.config.get("record_key", "alt")).lower()
            before_hold_enabled = bool(self.config.get("hold_to_record", False))
            before_hold_key = str(self.config.get("hold_record_key", "f8") or "f8").lower()
            before_middle_enabled = bool(self.config.get("middle_click_toggle_recording", False))
            before_middle_suppress = False
            before_provider = self._transcription_provider()
            before_model = str(self.config.get("whisper_model", "small") or "small")
            before_beam_size = int(self.config.get("whisper_beam_size", 3) or 3)
            before_condition_previous = bool(self.config.get("whisper_condition_on_previous_text", False))
            before_auto_prompt_hints = bool(self.config.get("whisper_auto_prompt_hints_enabled", True))
            before_hotwords_enabled = bool(self.config.get("whisper_hotwords_enabled", False))
            before_preload = bool(self.config.get("preload_model_at_startup", False))

            device = device_label_to_value.get(device_var.get(), "auto")
            config["input_device"] = int(device) if str(device).isdigit() else "auto"
            config["record_key"] = key_label_to_value.get(key_var.get(), "alt")
            config["hold_to_record"] = bool(hold_enabled_var.get())
            config["hold_record_key"] = (
                hold_key_label_to_value.get(hold_key_var.get(), hold_key_var.get().strip().lower()) or "f8"
            )
            config["double_tap_to_toggle"] = True
            config["middle_click_toggle_recording"] = bool(middle_click_var.get())
            config["middle_click_suppress_native"] = False
            config["transcription_provider"] = selected_provider()
            config["whisper_model"] = model_label_to_value.get(model_var.get(), "small")
            config["whisper_beam_size"] = int(beam_label_to_value.get(beam_var.get(), 3) or 3)
            config["whisper_condition_on_previous_text"] = bool(condition_previous_var.get())
            config["whisper_auto_prompt_hints_enabled"] = bool(auto_prompt_hints_var.get())
            config["whisper_hotwords_enabled"] = bool(hotwords_enabled_var.get())
            config["postprocess_mode"] = selected_postprocess()
            config["openai_compatible_base_url"] = ai_base_url_var.get().strip()
            config["openai_compatible_model"] = ai_model_var.get().strip() or "gpt-4.1-mini"
            config["openai_compatible_api_key_env"] = ai_key_env_var.get().strip() or "OPENAI_API_KEY"
            config["gemini_api_key_env"] = gemini_env_var.get().strip() or "GEMINI_API_KEY"
            config["preload_model_at_startup"] = bool(preload_var.get())
            config["launch_at_login"] = bool(launch_var.get())

            key_text = gemini_key_var.get().strip()
            if key_text and key_text != API_KEY_MASK and gemini_key_state["dirty"]:
                set_user_api_key(config["gemini_api_key_env"], key_text)
                gemini_key_state["dirty"] = False
                gemini_key_state["placeholder"] = True
                gemini_key_var.set(API_KEY_MASK)

            save_config(config, config_path)
            self.config.update(load_config(config_path))
            self._invalidate_whisper_hints()

            startup_result = ""
            try:
                from .setup import _apply_launch_at_login

                startup_result = _apply_launch_at_login(bool(config["launch_at_login"]))
            except Exception as error:
                startup_result = f"Login startup update failed: {error}"
                self._log(startup_result)

            if str(self.config.get("input_device", "auto")) != before_device:
                self.recorder = Recorder(
                    sample_rate=int(self.config.get("sample_rate", 16000)),
                    device=self.config.get("input_device", "auto"),
                )
                self._log(f"settings applied: input_device={self.config.get('input_device')}")

            if (
                str(self.config.get("record_key", "alt")).lower() != before_key
                or bool(self.config.get("hold_to_record", False)) != before_hold_enabled
                or str(self.config.get("hold_record_key", "f8") or "f8").lower() != before_hold_key
            ):
                self._restart_keyboard_listener()

            if (
                bool(self.config.get("middle_click_toggle_recording", False)) != before_middle_enabled
                or bool(self.config.get("middle_click_suppress_native", False)) != before_middle_suppress
            ):
                self._restart_mouse_listener()

            if self._transcription_provider() != before_provider:
                self._log(f"settings applied: transcription_provider={self._transcription_provider()}")

            if (
                str(self.config.get("whisper_model", "small") or "small") != before_model
                or int(self.config.get("whisper_beam_size", 3) or 3) != before_beam_size
                or bool(self.config.get("whisper_condition_on_previous_text", False)) != before_condition_previous
            ):
                self.transcriber = self._make_transcriber()
                self._model_warmup_thread = None
                self._log(
                    "settings applied: "
                    f"whisper_model={self.config.get('whisper_model')} "
                    f"beam_size={self.config.get('whisper_beam_size')} "
                    f"condition_on_previous_text={self.config.get('whisper_condition_on_previous_text')}"
                )
                if bool(self.config.get("preload_model_at_startup", False)):
                    self._start_model_warmup()

            if bool(self.config.get("preload_model_at_startup", False)) != before_preload:
                self._log(f"settings applied: preload_model_at_startup={self.config.get('preload_model_at_startup')}")
                if bool(self.config.get("preload_model_at_startup", False)):
                    self._start_model_warmup()

            if (
                bool(self.config.get("whisper_auto_prompt_hints_enabled", True)) != before_auto_prompt_hints
                or bool(self.config.get("whisper_hotwords_enabled", False)) != before_hotwords_enabled
            ):
                self._log(
                    "settings applied: "
                    f"whisper_auto_prompt_hints_enabled={self.config.get('whisper_auto_prompt_hints_enabled')} "
                    f"whisper_hotwords_enabled={self.config.get('whisper_hotwords_enabled')}"
                )

            refresh_api_status()
            status = "保存しました。"
            if startup_result:
                status += f" {startup_result}"
            status_var.set(status)
            self._notify("Koe Kichi settings", "Settings saved.")

        button_frame = ttk.Frame(main)
        button_frame.grid(row=17, column=0, columnspan=2, sticky=tk.EW, pady=(16, 0))
        ttk.Button(button_frame, text="保存", command=save_settings).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="閉じる", command=window.destroy).pack(side=tk.RIGHT)
        ttk.Label(main, textvariable=status_var).grid(row=18, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))

        provider_var.trace_add("write", sync_gemini_state)
        gemini_env_var.trace_add("write", refresh_api_status)
        gemini_key_var.trace_add("write", mark_key_dirty)
        postprocess_var.trace_add("write", sync_postprocess_state)
        gemini_key_entry.bind("<FocusIn>", clear_key_placeholder)
        sync_gemini_state()
        sync_hold_state()
        sync_middle_click_state()
        sync_postprocess_state()
        window.focus_force()

    def _restart_keyboard_listener(self) -> None:
        if self._keyboard_listener is not None:
            try:
                self._keyboard_listener.stop()
            except Exception as error:
                self._log(f"keyboard listener stop failed during settings reload: {error}")
            self._keyboard_listener = None
        self._start_keyboard_listener()

    def _restart_mouse_listener(self) -> None:
        if self._mouse_listener is not None:
            try:
                self._mouse_listener.stop()
            except Exception as error:
                self._log(f"middle-click listener stop failed during settings reload: {error}")
            self._mouse_listener = None
        self._start_mouse_listener()

    def _open_dictionary_window(self) -> None:
        try:
            import tkinter as tk
            from tkinter import messagebox
            from tkinter import ttk
        except Exception as error:
            self._log(f"dictionary window unavailable: {error}")
            return

        root = self._control_root
        if root is None:
            return

        window = tk.Toplevel(root)
        window.title("Koe Kichi Word Dictionary")
        window.geometry("520x420+120+120")
        window.minsize(460, 360)

        main = ttk.Frame(window, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        input_frame = ttk.LabelFrame(main, text="\u5358\u8a9e\u3092\u767b\u9332")
        input_frame.pack(fill=tk.X)

        ttk.Label(input_frame, text="\u8aad\u307f\u65b9\uff08Whisper\u306e\u8a8d\u8b58\u7d50\u679c\uff09").grid(row=0, column=0, sticky=tk.W, padx=8, pady=(8, 4))
        source_var = tk.StringVar()
        source_entry = ttk.Entry(input_frame, textvariable=source_var)
        source_entry.grid(row=0, column=1, sticky=tk.EW, padx=8, pady=(8, 4))

        ttk.Label(input_frame, text="\u5358\u8a9e\uff08\u51fa\u529b\u3057\u305f\u3044\u8868\u8a18\uff09").grid(row=1, column=0, sticky=tk.W, padx=8, pady=4)
        target_var = tk.StringVar()
        target_entry = ttk.Entry(input_frame, textvariable=target_var)
        target_entry.grid(row=1, column=1, sticky=tk.EW, padx=8, pady=4)
        input_frame.columnconfigure(1, weight=1)

        status_var = tk.StringVar(value="")

        list_frame = ttk.LabelFrame(main, text="\u767b\u9332\u6e08\u307f\u306e\u5358\u8a9e")
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        rule_list = tk.Listbox(list_frame, activestyle="dotbox")
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=rule_list.yview)
        rule_list.configure(yscrollcommand=scrollbar.set)
        rule_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=8)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=8)

        def refresh() -> None:
            try:
                self.dictionary.load()
                self._invalidate_whisper_hints()
            except Exception:
                pass
            rule_list.delete(0, tk.END)
            for rule in self.dictionary.replacements:
                source = str(rule.get("from", ""))
                target = str(rule.get("to", ""))
                rule_list.insert(tk.END, f"{source}  =>  {target}")

        def add_rule() -> None:
            source = source_var.get().strip()
            target = target_var.get().strip()
            if not source or not target:
                messagebox.showinfo("Koe Kichi", "\u8aad\u307f\u65b9\u3068\u5358\u8a9e\u3092\u5165\u529b\u3057\u3066\u304f\u3060\u3055\u3044\u3002", parent=window)
                return
            try:
                self.dictionary.load()
            except Exception:
                pass
            rules = self.dictionary.replacements
            replaced = False
            for rule in rules:
                if str(rule.get("from", "")) == source:
                    rule["to"] = target
                    rule["mode"] = "literal"
                    replaced = True
                    break
            if not replaced:
                rules.append({"from": source, "to": target, "mode": "literal"})
            self.dictionary.save()
            self._invalidate_whisper_hints()
            source_var.set("")
            target_var.set("")
            status_var.set("\u4fdd\u5b58\u3057\u307e\u3057\u305f")
            refresh()
            self._log(f"dictionary rule saved: {source} -> {target}")

        def delete_selected() -> None:
            selection = list(rule_list.curselection())
            if not selection:
                return
            index = int(selection[0])
            try:
                self.dictionary.load()
                rules = self.dictionary.replacements
                if 0 <= index < len(rules):
                    removed = rules.pop(index)
                    self.dictionary.save()
                    self._invalidate_whisper_hints()
                    status_var.set("\u524a\u9664\u3057\u307e\u3057\u305f")
                    self._log(f"dictionary rule removed: {removed}")
            finally:
                refresh()

        button_frame = ttk.Frame(main)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(button_frame, text="\u767b\u9332", command=add_rule).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="\u524a\u9664", command=delete_selected).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(button_frame, text="\u9589\u3058\u308b", command=window.destroy).pack(side=tk.RIGHT)
        ttk.Label(button_frame, textvariable=status_var).pack(side=tk.LEFT, padx=12)

        source_entry.focus_set()
        window.bind("<Return>", lambda _event: add_rule())
        refresh()

    def _open_history_window(self) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except Exception as error:
            self._log(f"history window unavailable: {error}")
            return

        root = self._control_root
        if root is None:
            return

        window = tk.Toplevel(root)
        window.title("Koe Kichi History")
        window.geometry("680x420+140+140")
        window.minsize(520, 320)

        main = ttk.Frame(window, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        status_var = tk.StringVar(value="\u5c65\u6b74\u3092\u30af\u30ea\u30c3\u30af\u3059\u308b\u3068\u30b3\u30d4\u30fc\u3057\u307e\u3059\u3002")
        ttk.Label(main, textvariable=status_var).pack(fill=tk.X, pady=(0, 8))

        list_frame = ttk.Frame(main)
        list_frame.pack(fill=tk.BOTH, expand=True)
        history_list = tk.Listbox(list_frame, activestyle="dotbox")
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=history_list.yview)
        history_list.configure(yscrollcommand=scrollbar.set)
        history_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        with self._history_lock:
            history = self._load_history_unlocked()

        def display_text(item: dict[str, Any]) -> str:
            text = str(item.get("out", "")).replace("\r", " ").replace("\n", " ").strip()
            if len(text) > 90:
                text = text[:87] + "..."
            return f"{item.get('time', '')}  {text}"

        for item in history:
            history_list.insert(tk.END, display_text(item))

        def copy_selected(_event: Any | None = None) -> None:
            selection = list(history_list.curselection())
            if not selection:
                return
            index = int(selection[0])
            if 0 <= index < len(history):
                text = str(history[index].get("out", ""))
                if text:
                    copy_text(text)
                    status_var.set("\u30b3\u30d4\u30fc\u3057\u307e\u3057\u305f")
                    self._log("history item copied")

        def clear_history() -> None:
            with self._history_lock:
                self._save_history_unlocked([])
            history.clear()
            history_list.delete(0, tk.END)
            status_var.set("\u5c65\u6b74\u3092\u524a\u9664\u3057\u307e\u3057\u305f")

        history_list.bind("<<ListboxSelect>>", copy_selected)
        history_list.bind("<Double-Button-1>", copy_selected)

        button_frame = ttk.Frame(main)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(button_frame, text="\u30b3\u30d4\u30fc", command=copy_selected).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="\u5c65\u6b74\u3092\u524a\u9664", command=clear_history).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(button_frame, text="\u9589\u3058\u308b", command=window.destroy).pack(side=tk.RIGHT)
    def _start_tray_icon(self) -> None:
        try:
            import pystray
            from PIL import Image
            from PIL import ImageDraw
        except Exception as error:
            self._log(f"tray icon unavailable: {error}")
            return

        def open_dictionary(_icon: Any, _item: Any) -> None:
            self._schedule_ui(self._open_dictionary_window)

        def open_history(_icon: Any, _item: Any) -> None:
            self._schedule_ui(self._open_history_window)

        def open_settings(_icon: Any, _item: Any) -> None:
            self._schedule_ui(self._open_settings_window)

        def run_model_setup(_icon: Any, _item: Any) -> None:
            self._run_model_setup()

        def exit_app(_icon: Any, _item: Any) -> None:
            self.stop()

        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((6, 6, 58, 58), fill=(39, 112, 214, 255))
        draw.rectangle((29, 18, 35, 42), fill=(255, 255, 255, 255))
        draw.arc((18, 24, 46, 52), 25, 155, fill=(255, 255, 255, 255), width=4)

        menu = pystray.Menu(
            pystray.MenuItem("Koe Kichi is running", None, enabled=False),
            pystray.MenuItem("\u8a2d\u5b9a...", open_settings),
            pystray.MenuItem("\u30e2\u30c7\u30eb\u30bb\u30c3\u30c8\u30a2\u30c3\u30d7...", run_model_setup),
            pystray.MenuItem("\u8f9e\u66f8\u767b\u9332...", open_dictionary),
            pystray.MenuItem("\u5c65\u6b74...", open_history),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", exit_app),
        )
        self._tray_icon = pystray.Icon("Koe Kichi", image, "Koe Kichi", menu)
        thread = threading.Thread(target=self._tray_icon.run, daemon=True)
        thread.start()
        self._log("tray icon started")

    def _notify(self, title: str, message: str) -> None:
        icon = self._tray_icon
        if icon is None:
            return
        try:
            icon.notify(message, title)
        except Exception:
            pass

    def _set_status(self, status: str) -> None:
        try:
            self._status_queue.put_nowait(status)
        except Exception:
            pass

    def _log(self, message: str) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            now = _datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"[{now}] {message}\n")
        except Exception:
            pass
        print(message)

    def _schedule_recording_timeout(self) -> None:
        self._cancel_recording_timeout()
        max_seconds = float(self.config.get("max_record_seconds", 60.0))
        if max_seconds <= 0:
            return

        def on_timeout() -> None:
            self._log(f"recording auto-stop after {max_seconds:g} seconds")
            self.stop_recording()

        timer = threading.Timer(max_seconds, on_timeout)
        timer.daemon = True
        self._recording_timer = timer
        timer.start()

    def _cancel_recording_timeout(self) -> None:
        timer = self._recording_timer
        self._recording_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _acquire_single_instance_lock(self) -> bool:
        try:
            lock_path = app_data_dir() / "koe-kichi.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            handle = lock_path.open("a+b")
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            self._lock_file_handle = handle
            return True
        except OSError:
            return False

    def _release_single_instance_lock(self) -> None:
        handle = self._lock_file_handle
        if handle is None:
            return
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            handle.close()
        except Exception:
            pass
        self._lock_file_handle = None


def _input_device_options() -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = [("auto", "Auto / Windows default microphone")]
    try:
        import sounddevice as sd

        for index, device in enumerate(sd.query_devices()):
            max_inputs = int(device.get("max_input_channels", 0))
            if max_inputs > 0:
                name = str(device.get("name", "")).strip() or f"Device {index}"
                options.append((str(index), f"{index}: {name}"))
    except Exception:
        pass
    return options


def _label_for_value(options: list[tuple[str, str]], value: str) -> str:
    for item_value, label in options:
        if str(item_value) == str(value):
            return label
    return options[0][1] if options else str(value)


def _matches_key(key: Any, configured: str, keyboard_module: Any) -> bool:
    aliases = {
        "alt": {keyboard_module.Key.alt, keyboard_module.Key.alt_l, keyboard_module.Key.alt_r},
        "option": {keyboard_module.Key.alt, keyboard_module.Key.alt_l, keyboard_module.Key.alt_r},
        "ctrl": {keyboard_module.Key.ctrl, keyboard_module.Key.ctrl_l, keyboard_module.Key.ctrl_r},
        "control": {keyboard_module.Key.ctrl, keyboard_module.Key.ctrl_l, keyboard_module.Key.ctrl_r},
        "shift": {keyboard_module.Key.shift, keyboard_module.Key.shift_l, keyboard_module.Key.shift_r},
    }
    if configured in aliases:
        return key in aliases[configured]
    key_name = getattr(key, "name", None)
    if key_name and key_name.lower() == configured:
        return True
    char = getattr(key, "char", None)
    return bool(char and char.lower() == configured)
