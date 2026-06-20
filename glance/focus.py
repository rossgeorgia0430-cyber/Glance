# -*- coding: utf-8 -*-
"""取呼出瞬间前台窗口所在目录(主要支持资源管理器)。

须在显示 Glance 窗口之前调用,此时前台仍是用户原来的窗口。
"""
import os

import win32gui

# 资源管理器文件夹窗口的类名
_EXPLORER_CLASSES = ("CabinetWClass", "ExploreWClass")


def _explorer_folder(hwnd):
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        shell = win32com.client.Dispatch("Shell.Application")
        for w in shell.Windows():
            try:
                if int(w.HWND) != int(hwnd):
                    continue
                path = w.Document.Folder.Self.Path
                if path and os.path.isdir(path):
                    return path
            except Exception:
                continue
    except Exception:
        return None
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
    return None


def foreground_folder():
    """前台资源管理器窗口的当前目录;无法判定时返回 None(=全局搜索)。"""
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        if win32gui.GetClassName(hwnd) in _EXPLORER_CLASSES:
            return _explorer_folder(hwnd)
    except Exception:
        return None
    return None
