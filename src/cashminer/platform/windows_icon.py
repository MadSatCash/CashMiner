"""Optional Windows-only taskbar/titlebar icon for the managed Chromium window.

Uses the standard-library Win32 API instead of pywebview/pythonnet. Failure to
apply the cosmetic icon never stops the web UI or miner. No process injection.
"""
from __future__ import annotations

import os
import time
from pathlib import Path


def apply_window_icon(browser_proc, icon_file: Path, timeout=9.0) -> bool:
    if os.name != 'nt' or not Path(icon_file).is_file():
        return False
    try:
        import ctypes
        from ctypes import wintypes
        u32=ctypes.WinDLL('user32',use_last_error=True)
        u32.LoadImageW.argtypes=[wintypes.HINSTANCE,wintypes.LPCWSTR,wintypes.UINT,
                                 ctypes.c_int,ctypes.c_int,wintypes.UINT]
        u32.LoadImageW.restype=wintypes.HANDLE
        u32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        u32.GetWindowThreadProcessId.restype=wintypes.DWORD
        u32.GetWindowTextLengthW.argtypes=[wintypes.HWND]
        u32.GetWindowTextLengthW.restype=ctypes.c_int
        u32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        u32.GetWindowTextW.restype=ctypes.c_int
        u32.IsWindowVisible.argtypes=[wintypes.HWND]
        u32.IsWindowVisible.restype=wintypes.BOOL
        u32.SendMessageTimeoutW.argtypes=[wintypes.HWND,wintypes.UINT,
            wintypes.WPARAM,wintypes.LPARAM,wintypes.UINT,wintypes.UINT,
            ctypes.POINTER(ctypes.c_size_t)]
        u32.SendMessageTimeoutW.restype=wintypes.LPARAM
        # Loaded USER handles are kept valid for this process lifetime.
        source=str(icon_file.resolve())
        small=u32.LoadImageW(None,source,1,16,16,0x10) # IMAGE_ICON, LR_LOADFROMFILE
        large=u32.LoadImageW(None,source,1,32,32,0x10)
        if not small or not large:
            return False
        callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
        u32.EnumWindows.argtypes=[callback,wintypes.LPARAM]
        u32.EnumWindows.restype=wintypes.BOOL
        match={'found':False}

        def consider(hwnd,_):
            pid=wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            if pid.value!=browser_proc.pid or not u32.IsWindowVisible(hwnd):
                return True
            length=u32.GetWindowTextLengthW(hwnd)
            if not length or length>1024:
                return True
            title=ctypes.create_unicode_buffer(length+1)
            u32.GetWindowTextW(hwnd,title,length+1)
            if 'CashMiner' not in title.value:
                return True
            for icon_type,icon in ((0,small),(1,large)):
                result=ctypes.c_size_t()
                u32.SendMessageTimeoutW(hwnd,0x0080,icon_type,int(icon),0x0002,500,ctypes.byref(result))
            match['found']=True
            return False

        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline and browser_proc.poll() is None:
            u32.EnumWindows(callback(consider),0)
            if match['found']:
                return True
            time.sleep(.25)
        return False
    except (OSError,AttributeError,ValueError,TypeError):
        return False
