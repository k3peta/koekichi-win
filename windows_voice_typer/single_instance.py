from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


ERROR_ALREADY_EXISTS = 183
_MUTEX_HANDLE: int | None = None


def acquire_single_instance(name: str = "Local\\KoeKichiWinSingleInstance") -> bool:
    if os.name != "nt":
        return True
    global _MUTEX_HANDLE
    if _MUTEX_HANDLE:
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            return True
        if int(kernel32.GetLastError()) == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = int(handle)
        return True
    except Exception:
        return True
