# -*- coding: utf-8 -*-
"""全局热键(默认 Ctrl+Alt+S)—— 独立线程跑 RegisterHotKey + 消息循环。"""
import ctypes
import threading
from ctypes import wintypes

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32

_MOD_ALT = 0x0001
_MOD_CONTROL = 0x0002
_MOD_NOREPEAT = 0x4000
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_HOTKEY_ID = 1
_VK_S = 0x53

_user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
_user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
_user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]


class HotkeyThread(threading.Thread):
    def __init__(self, callback, mods=_MOD_CONTROL | _MOD_ALT, vk=_VK_S):
        super().__init__(daemon=True, name="GlanceHotkey")
        self._callback = callback
        self._mods = mods | _MOD_NOREPEAT
        self._vk = vk
        self._tid = None
        self.registered = False

    def run(self):
        self._tid = _kernel32.GetCurrentThreadId()
        if not _user32.RegisterHotKey(None, _HOTKEY_ID, self._mods, self._vk):
            self.registered = False
            return
        self.registered = True
        msg = wintypes.MSG()
        while True:
            ret = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret in (0, -1):
                break
            if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                try:
                    self._callback()
                except Exception:
                    pass
        _user32.UnregisterHotKey(None, _HOTKEY_ID)

    def stop(self):
        if self._tid:
            _user32.PostThreadMessageW(self._tid, _WM_QUIT, 0, 0)
