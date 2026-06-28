from __future__ import annotations

import ctypes
from ctypes import wintypes
import time
from typing import Any


GA_ROOT = 2
SW_RESTORE = 9


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", RECT),
    ]


def get_foreground_window() -> int:
    try:
        hwnd = int(ctypes.windll.user32.GetForegroundWindow())
        return _root_window(hwnd)
    except Exception:
        return 0


def get_focus_window() -> int:
    try:
        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow()
        if not foreground:
            return 0
        thread_id = user32.GetWindowThreadProcessId(foreground, None)
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return int(info.hwndFocus or 0)
    except Exception:
        return 0
    return 0


def get_caret_screen_rect(target_hwnd: int | None = None) -> tuple[int, int, int, int] | None:
    try:
        user32 = ctypes.windll.user32
        hwnd = int(target_hwnd or user32.GetForegroundWindow() or 0)
        if not hwnd:
            return None
        if not user32.IsWindow(hwnd):
            return None
        thread_id = user32.GetWindowThreadProcessId(hwnd, None)
        if not thread_id:
            return None
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return None
        caret_hwnd = int(info.hwndCaret or info.hwndFocus or 0)
        if not caret_hwnd:
            return None
        rect = info.rcCaret
        left = int(rect.left)
        top = int(rect.top)
        right = int(rect.right)
        bottom = int(rect.bottom)
        if left < 0 and top < 0:
            return None
        if left == right and top == bottom:
            right = left + 2
            bottom = top + 18

        point = wintypes.POINT(left, top)
        if not user32.ClientToScreen(caret_hwnd, ctypes.byref(point)):
            return None
        screen_left = int(point.x)
        screen_top = int(point.y)
        if screen_left < 0 and screen_top < 0:
            return None
        return (
            screen_left,
            screen_top,
            screen_left + max(2, right - left),
            screen_top + max(18, bottom - top),
        )
    except Exception:
        return None


def get_text_target_screen_rect(target_hwnd: int | None = None) -> tuple[int, int, int, int] | None:
    return get_caret_screen_rect(target_hwnd) or _get_uia_focused_text_rect(target_hwnd)


def _get_uia_focused_text_rect(target_hwnd: int | None = None) -> tuple[int, int, int, int] | None:
    try:
        import comtypes.client

        try:
            comtypes.client.GetModule("UIAutomationCore.dll")
        except Exception:
            pass
        from comtypes.gen import UIAutomationClient as UIA

        automation = comtypes.client.CreateObject(
            "{FF48DBA4-60EF-4201-AA87-54103EEF594E}",
            interface=UIA.IUIAutomation,
        )
        element = _uia_focused_text_element(automation, UIA, target_hwnd)
        if not element:
            return None
        selection = _uia_selection_rect(element, UIA)
        if selection is not None:
            return selection
        return _normalize_screen_rect(element.CurrentBoundingRectangle)
    except Exception:
        return None


def _uia_focused_text_element(automation: Any, UIA: Any, target_hwnd: int | None) -> Any | None:
    root = None
    if target_hwnd:
        try:
            root = automation.ElementFromHandle(int(target_hwnd))
        except Exception:
            root = None
    if root is not None:
        try:
            condition = automation.CreatePropertyCondition(UIA.UIA_HasKeyboardFocusPropertyId, True)
            focused_child = root.FindFirst(UIA.TreeScope_Descendants, condition)
            if focused_child is not None and _uia_is_text_element(focused_child, UIA):
                return focused_child
        except Exception:
            pass
    try:
        focused = automation.GetFocusedElement()
    except Exception:
        focused = None
    if focused is not None and _uia_is_text_element(focused, UIA):
        return focused
    return None


def _uia_is_text_element(element: Any, UIA: Any) -> bool:
    try:
        if int(element.CurrentControlType) in (UIA.UIA_EditControlTypeId, UIA.UIA_DocumentControlTypeId):
            return True
    except Exception:
        pass
    try:
        element.GetCurrentPattern(UIA.UIA_TextPatternId)
        return True
    except Exception:
        return False


def _uia_selection_rect(element: Any, UIA: Any) -> tuple[int, int, int, int] | None:
    try:
        pattern = element.GetCurrentPattern(UIA.UIA_TextPatternId)
        text_pattern = pattern.QueryInterface(UIA.IUIAutomationTextPattern)
        ranges = text_pattern.GetSelection()
        if not ranges or ranges.Length <= 0:
            return None
        text_range = ranges.GetElement(0)
        raw_rects = list(text_range.GetBoundingRectangles())
    except Exception:
        return None
    for index in range(0, len(raw_rects) - 3, 4):
        left = int(raw_rects[index])
        top = int(raw_rects[index + 1])
        width = int(raw_rects[index + 2])
        height = int(raw_rects[index + 3])
        rect = _normalize_rect_values(left, top, left + width, top + height)
        if rect is not None:
            return rect
    return None


def _normalize_screen_rect(rect: Any) -> tuple[int, int, int, int] | None:
    try:
        return _normalize_rect_values(
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )
    except Exception:
        return None


def _normalize_rect_values(left: int, top: int, right: int, bottom: int) -> tuple[int, int, int, int] | None:
    if left <= 0 and top <= 0:
        return None
    width = right - left
    height = bottom - top
    if width <= 0 and height <= 0:
        return None
    return (
        left,
        top,
        left + max(2, width),
        top + max(18, height),
    )


def paste_text(
    text: str,
    *,
    preserve_clipboard: bool = True,
    restore_delay: float = 0.25,
    target_hwnd: int | None = None,
    target_focus_hwnd: int | None = None,
) -> None:
    import pyperclip
    from pynput.keyboard import Controller, Key

    previous = pyperclip.paste() if preserve_clipboard else None
    pyperclip.copy(text)
    if target_hwnd:
        _activate_window(int(target_hwnd), int(target_focus_hwnd or 0))
    time.sleep(0.18)
    keyboard = Controller()
    try:
        keyboard.press(Key.ctrl)
        keyboard.press("v")
        time.sleep(0.02)
    finally:
        for key in ("v", Key.ctrl, Key.ctrl_l, Key.ctrl_r):
            try:
                keyboard.release(key)
            except Exception:
                pass
    time.sleep(0.05)
    if previous is not None:
        time.sleep(restore_delay)
        pyperclip.copy(previous)


def restore_focus(target_hwnd: int | None, target_focus_hwnd: int | None = None) -> bool:
    if not target_hwnd:
        return False
    return _activate_window(int(target_hwnd), int(target_focus_hwnd or 0))


def clear_alt_menu_focus(target_hwnd: int | None, target_focus_hwnd: int | None = None) -> bool:
    if not target_hwnd:
        return False
    restored = _activate_window(int(target_hwnd), int(target_focus_hwnd or 0))
    try:
        from pynput.keyboard import Controller
        from pynput.keyboard import Key

        keyboard = Controller()
        for key in (Key.alt, Key.alt_l, Key.alt_r):
            try:
                keyboard.release(key)
            except Exception:
                pass
        time.sleep(0.03)
        keyboard.press(Key.esc)
        time.sleep(0.02)
        keyboard.release(Key.esc)
        time.sleep(0.06)
    except Exception:
        return restored
    return _activate_window(int(target_hwnd), int(target_focus_hwnd or 0)) or restored


def copy_text(text: str) -> None:
    import pyperclip

    pyperclip.copy(text)


def _root_window(hwnd: int) -> int:
    if not hwnd:
        return 0
    try:
        root = ctypes.windll.user32.GetAncestor(hwnd, GA_ROOT)
        return int(root or hwnd)
    except Exception:
        return int(hwnd)


def _activate_window(hwnd: int, focus_hwnd: int = 0) -> bool:
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        root_hwnd = _root_window(hwnd)
        if not user32.IsWindow(root_hwnd):
            return False

        try:
            user32.AllowSetForegroundWindow(0xFFFFFFFF)
        except Exception:
            pass

        try:
            if user32.IsIconic(root_hwnd):
                user32.ShowWindow(root_hwnd, SW_RESTORE)
        except Exception:
            pass
        current_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(root_hwnd, None)
        foreground = user32.GetForegroundWindow()
        foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        attached_target = False
        attached_foreground = False
        if target_thread and target_thread != current_thread:
            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
        if foreground_thread and foreground_thread not in (current_thread, target_thread):
            attached_foreground = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
        try:
            user32.BringWindowToTop(root_hwnd)
            user32.SetForegroundWindow(root_hwnd)
            if focus_hwnd and user32.IsWindow(focus_hwnd):
                focus_root = _root_window(focus_hwnd)
                if focus_root == root_hwnd or user32.IsChild(root_hwnd, focus_hwnd):
                    user32.SetFocus(focus_hwnd)
        finally:
            if attached_foreground:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
            if attached_target:
                user32.AttachThreadInput(current_thread, target_thread, False)
        return _root_window(int(user32.GetForegroundWindow())) == root_hwnd
    except Exception:
        return False
