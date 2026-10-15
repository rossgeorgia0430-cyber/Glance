# -*- coding: utf-8 -*-
"""全局热键 Ctrl+Alt+S —— 独立线程跑 RegisterHotKey + 消息循环(WM_HOTKEY 只投给注册线程)。"""
import ctypes
import logging
import threading
from ctypes import wintypes

log = logging.getLogger(__name__)

_user32 = ctypes.WinDLL("user32", use_last_error=True)
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
    def __init__(self, callback):
        super().__init__(daemon=True, name="GlanceHotkey")
        self._callback = callback
        self._tid = None
        self._registered = False
        self._ready = threading.Event()

    def run(self):
        self._tid = _kernel32.GetCurrentThreadId()
        self._registered = bool(_user32.RegisterHotKey(
            None, _HOTKEY_ID, _MOD_CONTROL | _MOD_ALT | _MOD_NOREPEAT, _VK_S))
        error = ctypes.get_last_error()
        self._ready.set()
        if not self._registered:
            log.warning("注册全局热键失败 (错误码 %d)", error)
            return
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) not in (0, -1):
            if msg.message == _WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                try:
                    self._callback()
                except Exception:  # noqa: BLE001  一次呼出失败不能让消息循环退出、热键失效
                    log.exception("热键呼出失败")
        _user32.UnregisterHotKey(None, _HOTKEY_ID)

    def wait_registered(self, timeout):
        self._ready.wait(timeout)
        return self._registered

    def stop(self):
        if self._tid is None:
            return
        self._ready.wait(1.0)
        _user32.PostThreadMessageW(self._tid, _WM_QUIT, 0, 0)
