from __future__ import annotations

import ctypes
import threading
import time
from typing import Any
from typing import Callable


Callback = Callable[..., None]
TargetProvider = Callable[[], tuple[int, int]]


VK_CODES: dict[str, int] = {
    "alt": 0x12,
    "option": 0x12,
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
    "middle_mouse": 0x04,
}


class PollingDoubleTapListener:
    def __init__(
        self,
        *,
        key: str,
        interval_seconds: float,
        callback: Callback,
        get_target: TargetProvider | None = None,
        poll_seconds: float = 0.025,
    ):
        self.key = key.strip().lower()
        self.vk_code = _vk_code_for_key(self.key)
        self.interval_seconds = max(0.05, float(interval_seconds))
        self.callback = callback
        self.get_target = get_target
        self.poll_seconds = max(0.01, float(poll_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_down = False
        self._last_tap_at = 0.0
        self._last_target: tuple[int, int] = (0, 0)
        self._pending_target: tuple[int, int] | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=f"KoeKichiPollDoubleTap-{self.key}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_seconds):
            now = time.monotonic()
            down = _is_down(self.vk_code)
            if not down and not self._last_down:
                if self._last_tap_at and now - self._last_tap_at > self.interval_seconds:
                    self._last_tap_at = 0.0
                    self._pending_target = None
                self._last_target = self._read_target()
            elif not self._last_down and down:
                if self._pending_target is None:
                    self._pending_target = self._last_target or self._read_target()
            if self._last_down and not down:
                if self._last_tap_at and now - self._last_tap_at <= self.interval_seconds:
                    target = self._pending_target or self._last_target
                    self._last_tap_at = 0.0
                    self._pending_target = None
                    if self.get_target is None:
                        _call_async(self.callback)
                    else:
                        _call_async(self.callback, *target)
                else:
                    self._last_tap_at = now
            self._last_down = down

    def _read_target(self) -> tuple[int, int]:
        if self.get_target is None:
            return (0, 0)
        try:
            hwnd, focus_hwnd = self.get_target()
            return int(hwnd or 0), int(focus_hwnd or 0)
        except Exception:
            return (0, 0)


class PollingHoldListener:
    def __init__(
        self,
        *,
        key: str,
        start_delay_seconds: float,
        on_start: Callback,
        on_stop: Callback,
        poll_seconds: float = 0.025,
    ):
        self.key = key.strip().lower()
        self.vk_code = _vk_code_for_key(self.key)
        self.start_delay_seconds = max(0.0, float(start_delay_seconds))
        self.on_start = on_start
        self.on_stop = on_stop
        self.poll_seconds = max(0.01, float(poll_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._pressed_at = 0.0
        self._started = False

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=f"KoeKichiPollHold-{self.key}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_seconds):
            down = _is_down(self.vk_code)
            now = time.monotonic()
            if down:
                if not self._pressed_at:
                    self._pressed_at = now
                    self._started = False
                if not self._started and now - self._pressed_at >= self.start_delay_seconds:
                    self._started = True
                    _call_async(self.on_start)
            else:
                if self._started:
                    _call_async(self.on_stop)
                self._pressed_at = 0.0
                self._started = False


class PollingClickListener:
    def __init__(
        self,
        *,
        key: str,
        callback: Callback,
        debounce_seconds: float = 0.45,
        poll_seconds: float = 0.02,
    ):
        self.key = key.strip().lower()
        self.vk_code = _vk_code_for_key(self.key)
        self.callback = callback
        self.debounce_seconds = max(0.05, float(debounce_seconds))
        self.poll_seconds = max(0.01, float(poll_seconds))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_down = False
        self._last_click_at = 0.0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=f"KoeKichiPollClick-{self.key}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.wait(self.poll_seconds):
            down = _is_down(self.vk_code)
            if self._last_down and not down:
                now = time.monotonic()
                if now - self._last_click_at >= self.debounce_seconds:
                    self._last_click_at = now
                    _call_async(self.callback)
            self._last_down = down


def _vk_code_for_key(key: str) -> int:
    if key in VK_CODES:
        return VK_CODES[key]
    if len(key) == 1:
        return ord(key.upper())
    raise ValueError(f"Unsupported polling input key: {key}")


def _is_down(vk_code: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(int(vk_code)) & 0x8000)


def _call_async(callback: Callback, *args: Any) -> None:
    threading.Thread(target=callback, args=args, daemon=True).start()
