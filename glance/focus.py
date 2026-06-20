# -*- coding: utf-8 -*-
"""取呼出瞬间前台窗口所在目录(主要支持资源管理器)。

须在显示 Glance 窗口之前抓取前台句柄(此时前台仍是用户原来的窗口);
Shell COM 解析目录相对慢,放到后台线程做(见 app.summon),避免拖慢唤出。
"""
import os

import win32gui

# 资源管理器文件夹窗口的类名
_EXPLORER_CLASSES = ("CabinetWClass", "ExploreWClass")


def foreground_explorer_hwnd():
    """若前台是资源管理器窗口,返回其句柄,否则 None。极快(纯 Win32,无 COM)。"""
    try:
        hwnd = win32gui.GetForegroundWindow()
        if hwnd and win32gui.GetClassName(hwnd) in _EXPLORER_CLASSES:
            return hwnd
    except Exception:
        pass
    return None


def explorer_folder_for(hwnd):
    """用 Shell COM 解析某资源管理器窗口的当前目录;失败返回 None。

    关键:用 dynamic.Dispatch(纯后期绑定),不走 win32com 的 gen_py 缓存。
    打包后(PyInstaller)gen_py 缓存通常无法生成/持久化,client.Dispatch 会
    每次唤出都极慢甚至抛错 —— 这正是打包版"Ctrl+Alt+S 唤出很慢、且不按当前
    目录搜索(退回全局)"的根因。dynamic 版始终快且打包安全。
    """
    if not hwnd:
        return None
    import pythoncom
    from win32com.client import dynamic
    pythoncom.CoInitialize()
    try:
        shell = dynamic.Dispatch("Shell.Application")
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
    """前台资源管理器窗口的当前目录;无法判定时返回 None(=全局搜索)。

    同步版(抓句柄 + COM 解析一步到位),保留作兼容/直接调用;
    呼出路径改走 foreground_explorer_hwnd + explorer_folder_for 的异步拆分。
    """
    return explorer_folder_for(foreground_explorer_hwnd())
