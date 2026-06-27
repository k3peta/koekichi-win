from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes
from typing import Callable


HC_ACTION = 0
WH_MOUSE_LL = 14
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_QUIT = 0x0012


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


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


LowLevelMouseProc = ctypes.WINFUNCTYPE(
    wintypes.LPARAM,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


TargetProvider = Callable[[], tuple[int, int]]
ClickCallback = Callable[[int, int], None]


class MiddleClickHook:
    def __init__(
        self,
        *,
        get_target: TargetProvider,
        on_middle_click: ClickCallback,
        suppress_native: bool = False,
        debounce_seconds: float = 0.45,
    ):
        self.get_target = get_target
        self.on_middle_click = on_middle_click
        self.suppress_native = suppress_native
        self.debounce_seconds = debounce_seconds
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._callback_thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook = None
        self._install_error = ""
        self._proc_ref = None
        self._callback_queue: queue.SimpleQueue[None | tuple[int, int]] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._button_down = False
        self._last_click_at = 0.0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._callback_thread = threading.Thread(target=self._run_callbacks, name="KoeKichiMiddleClickCallback", daemon=True)
        self._callback_thread.start()
        self._thread = threading.Thread(target=self._run, name="KoeKichiMiddleClickHook", daemon=True)
        self._thread.start()
        if not self._ready_event.wait(2.0):
            self.stop()
            raise RuntimeError("Middle-click hook did not start")
        if not self._hook:
            detail = f": {self._install_error}" if self._install_error else ""
            self.stop()
            raise RuntimeError(f"Middle-click hook could not be installed{detail}")

    def stop(self) -> None:
        self._stop_event.set()
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
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, LowLevelMouseProc, wintypes.HINSTANCE, wintypes.DWORD]
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
        self._proc_ref = LowLevelMouseProc(self._mouse_proc)
        module = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc_ref, module, 0)
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

    def _mouse_proc(self, n_code: int, w_param: int, l_param: int) -> int:
        user32 = ctypes.windll.user32
        if n_code == HC_ACTION and int(w_param) in (WM_MBUTTONDOWN, WM_MBUTTONUP):
            self._handle_middle_event(int(w_param))
            if self.suppress_native:
                return 1
        return int(user32.CallNextHookEx(self._hook, n_code, w_param, l_param))

    def _handle_middle_event(self, message: int) -> None:
        if message == WM_MBUTTONDOWN:
            with self._lock:
                if self._button_down:
                    return
                self._button_down = True
            return

        if message != WM_MBUTTONUP:
            return

        now = time.monotonic()
        with self._lock:
            if not self._button_down:
                return
            self._button_down = False
            if now - self._last_click_at < self.debounce_seconds:
                return
            self._last_click_at = now

        self._callback_queue.put((0, 0))

    def _run_callbacks(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._callback_queue.get()
            except Exception:
                continue
            if item is None:
                break
            try:
                target_hwnd, target_focus_hwnd = self.get_target()
            except Exception:
                target_hwnd, target_focus_hwnd = item
            try:
                self.on_middle_click(target_hwnd, target_focus_hwnd)
            except Exception:
                pass
