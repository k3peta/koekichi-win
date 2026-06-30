from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes
from typing import Callable


HC_ACTION = 0
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

VK_MENU = 0x12
VK_LMENU = 0xA4
VK_RMENU = 0xA5


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
    wintypes.LPARAM,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


TargetProvider = Callable[[], tuple[int, int]]
DoubleTapCallback = Callable[[int, int], None]
HoldCallback = Callable[[], None]
SingleTapCallback = Callable[[], None]


class AltActivationHook:
    def __init__(
        self,
        *,
        interval_seconds: float,
        get_target: TargetProvider,
        on_double_tap: DoubleTapCallback | None = None,
        hold_start_delay_seconds: float | None = None,
        on_hold_start: HoldCallback | None = None,
        on_hold_stop: HoldCallback | None = None,
        on_single_tap: SingleTapCallback | None = None,
        single_tap_delay_seconds: float = 0.08,
    ):
        self.interval_seconds = max(0.05, float(interval_seconds))
        self.get_target = get_target
        self.on_double_tap = on_double_tap
        self.hold_start_delay_seconds = max(0.0, float(hold_start_delay_seconds or 0.0))
        self.on_hold_start = on_hold_start
        self.on_hold_stop = on_hold_stop
        self.on_single_tap = on_single_tap
        self.single_tap_delay_seconds = max(0.0, float(single_tap_delay_seconds))
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._callback_thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._install_error = ""
        self._proc_ref = None
        self._callback_queue: queue.SimpleQueue[tuple[str, tuple[int, int] | None] | None] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._key_down = False
        self._hold_started = False
        self._hold_timer: threading.Timer | None = None
        self._single_tap_timer: threading.Timer | None = None
        self._last_tap_at = 0.0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._callback_thread = threading.Thread(target=self._run_callbacks, name="KoeKichiAltCallback", daemon=True)
        self._callback_thread.start()
        self._thread = threading.Thread(target=self._run, name="KoeKichiAltHook", daemon=True)
        self._thread.start()
        if not self._ready_event.wait(2.0):
            self.stop()
            raise RuntimeError("Alt hook did not start")
        if not self._hook:
            detail = f": {self._install_error}" if self._install_error else ""
            self.stop()
            raise RuntimeError(f"Alt hook could not be installed{detail}")

    def stop(self) -> None:
        self._stop_event.set()
        self._cancel_hold_timer()
        self._cancel_single_tap_timer()
        if self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        self._thread = None
        self._callback_queue.put(None)
        callback_thread = self._callback_thread
        if callback_thread is not None and callback_thread.is_alive():
            callback_thread.join(timeout=1.0)
        self._callback_thread = None

    def _run(self) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = wintypes.LPARAM
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
        user32.DispatchMessageW.restype = wintypes.LPARAM

        self._thread_id = int(kernel32.GetCurrentThreadId())
        self._proc_ref = LowLevelKeyboardProc(self._keyboard_proc)
        module = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc_ref, module, 0)
        if not self._hook:
            error_code = ctypes.get_last_error()
            self._install_error = f"WinError {error_code}"
        self._ready_event.set()
        if not self._hook:
            return
        msg = MSG()
        try:
            while not self._stop_event.is_set():
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result in (0, -1):
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            if self._hook:
                try:
                    user32.UnhookWindowsHookEx(self._hook)
                except Exception:
                    pass
            self._hook = None

    def _keyboard_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        user32 = ctypes.windll.user32
        if n_code == HC_ACTION:
            try:
                event = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if int(event.vkCode) in (VK_MENU, VK_LMENU, VK_RMENU):
                    self._handle_alt_event(int(w_param))
                    return 1
            except Exception:
                pass
        return int(user32.CallNextHookEx(self._hook, n_code, w_param, l_param))

    def _handle_alt_event(self, message: int) -> None:
        now = time.monotonic()
        if message in (WM_KEYDOWN, WM_SYSKEYDOWN):
            with self._lock:
                if self._key_down:
                    return
                self._cancel_single_tap_timer_locked()
                self._key_down = True
                self._hold_started = False
                self._schedule_hold_timer_locked()
            return

        if message not in (WM_KEYUP, WM_SYSKEYUP):
            return

        should_toggle = False
        should_stop_hold = False
        with self._lock:
            if not self._key_down:
                return
            self._key_down = False
            self._cancel_hold_timer_locked()
            if self._hold_started:
                should_stop_hold = True
                self._hold_started = False
            last_tap_at = self._last_tap_at
            if self.on_double_tap and last_tap_at and now - last_tap_at <= self.interval_seconds:
                self._last_tap_at = 0.0
                self._cancel_single_tap_timer_locked()
                should_toggle = True
            else:
                self._last_tap_at = now if self.on_double_tap else 0.0
                if not should_stop_hold:
                    self._schedule_single_tap_timer_locked()

        if should_stop_hold:
            self._callback_queue.put(("hold_stop", None))
        if should_toggle:
            self._callback_queue.put(("double_tap", (0, 0)))

    def _schedule_hold_timer_locked(self) -> None:
        if self.on_hold_start is None:
            return
        self._cancel_hold_timer_locked()
        timer = threading.Timer(self.hold_start_delay_seconds, self._maybe_start_hold)
        timer.daemon = True
        self._hold_timer = timer
        timer.start()

    def _cancel_hold_timer(self) -> None:
        with self._lock:
            self._cancel_hold_timer_locked()

    def _cancel_hold_timer_locked(self) -> None:
        timer = self._hold_timer
        self._hold_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _schedule_single_tap_timer_locked(self) -> None:
        if self.on_single_tap is None:
            return
        self._cancel_single_tap_timer_locked()
        timer = threading.Timer(self.single_tap_delay_seconds, self._run_single_tap)
        timer.daemon = True
        self._single_tap_timer = timer
        timer.start()

    def _cancel_single_tap_timer(self) -> None:
        with self._lock:
            self._cancel_single_tap_timer_locked()

    def _cancel_single_tap_timer_locked(self) -> None:
        timer = self._single_tap_timer
        self._single_tap_timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _maybe_start_hold(self) -> None:
        with self._lock:
            self._hold_timer = None
            if self._stop_event.is_set() or not self._key_down or self._hold_started:
                return
            self._hold_started = True
        self._callback_queue.put(("hold_start", None))

    def _run_single_tap(self) -> None:
        with self._lock:
            self._single_tap_timer = None
            if self._stop_event.is_set() or self._key_down:
                return
        self._callback_queue.put(("single_tap", None))

    def _run_callbacks(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._callback_queue.get()
            except Exception:
                continue
            if item is None:
                break
            event_name, payload = item
            if event_name == "double_tap":
                if self.on_double_tap is None:
                    continue
                try:
                    target_hwnd, target_focus_hwnd = self.get_target()
                except Exception:
                    target_hwnd, target_focus_hwnd = payload or (0, 0)
                try:
                    self.on_double_tap(target_hwnd, target_focus_hwnd)
                except Exception:
                    pass
                continue
            if event_name == "hold_start" and self.on_hold_start is not None:
                try:
                    self.on_hold_start()
                except Exception:
                    pass
                continue
            if event_name == "hold_stop" and self.on_hold_stop is not None:
                try:
                    self.on_hold_stop()
                except Exception:
                    pass
                continue
            if event_name == "single_tap" and self.on_single_tap is not None:
                try:
                    self.on_single_tap()
                except Exception:
                    pass


class AltDoubleTapHook(AltActivationHook):
    def __init__(
        self,
        *,
        interval_seconds: float,
        get_target: TargetProvider,
        on_double_tap: DoubleTapCallback,
    ):
        super().__init__(
            interval_seconds=interval_seconds,
            get_target=get_target,
            on_double_tap=on_double_tap,
        )
