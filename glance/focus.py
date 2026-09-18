# -*- coding: utf-8 -*-
"""取呼出瞬间前台窗口所在目录(主要支持资源管理器)。

须在显示 Glance 窗口之前抓取前台句柄(此时前台仍是用户原来的窗口);
Shell COM 解析目录相对慢,放到后台线程做(见 app.summon),避免拖慢唤出。
"""
import logging
import os

import pywintypes
import win32gui

log = logging.getLogger(__name__)

# 资源管理器文件夹窗口的类名
_EXPLORER_CLASSES = ("CabinetWClass", "ExploreWClass")
# 每个标签页一个的子窗口;Win11 多标签时所有标签共用顶层 HWND,只能靠它区分
_TAB_CLASS = "ShellTabWindowClass"


def foreground_explorer_hwnd():
    """若前台是资源管理器窗口,返回其句柄,否则 None。极快(纯 Win32,无 COM)。"""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    try:
        class_name = win32gui.GetClassName(hwnd)
    except pywintypes.error:
        return None  # 窗口恰好在两次调用之间关闭
    return hwnd if class_name in _EXPLORER_CLASSES else None


def _tab_window(shell_window):
    """Shell.Application 窗口项所在标签页的 ShellTabWindowClass 句柄。"""
    import pythoncom
    from win32com.shell import shell
    browser = shell_window._oleobj_.QueryInterface(pythoncom.IID_IServiceProvider).QueryService(
        shell.SID_STopLevelBrowser, shell.IID_IShellBrowser)
    return browser.GetWindow()


def explorer_folder_for(hwnd):
    """用 Shell COM 解析某资源管理器窗口当前标签页的目录;失败返回 None。

    用 dynamic.Dispatch(纯后期绑定),不走 win32com 的 gen_py 缓存:打包后该缓存
    通常无法生成或持久化,client.Dispatch 会每次都极慢甚至抛错。
    win32com 在此处才导入,不拖慢首次呼出。
    """
    import pythoncom
    from win32com.client import dynamic
    pythoncom.CoInitialize()
    try:
        # 当前标签的标签窗口在同级子窗口里 z 序最前
        active_tab = win32gui.FindWindowEx(hwnd, 0, _TAB_CLASS, None)
        for w in dynamic.Dispatch("Shell.Application").Windows():
            try:
                if int(w.HWND) != int(hwnd) or _tab_window(w) != active_tab:
                    continue
                path = w.Document.Folder.Self.Path
            except (pywintypes.com_error, AttributeError):
                continue  # 非文件夹视图(控制面板等)或正在关闭的窗口取不到 Folder
            if path and os.path.isdir(path):
                return path
    except pywintypes.com_error:
        log.warning("Shell COM 解析 Explorer 目录失败", exc_info=True)
    finally:
        pythoncom.CoUninitialize()
    return None
