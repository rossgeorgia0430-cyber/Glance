# -*- coding: utf-8 -*-
"""
Glance 常驻主程序。

单实例常驻:后台持有全局热键 + 托盘,窗口隐藏/显示而非创建/销毁。
- 无参启动:显示窗口(手动双击快捷方式)。
- --tray 启动:隐藏到托盘(登录自启用)。
- 已有实例时再次启动:通知其显示并退出。
"""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes

import webview

from . import everything, frecency, settings
from .window import NativeWindow, set_immersive_dark
# 注意:focus / hotkey / tray / pyperclip 均延迟导入(见下),
# 避免在显示窗口前就加载 win32com / pystray / PIL,拖慢启动。

_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX = os.path.join(_HERE, "assets", "index.html")
if not os.path.exists(_INDEX):  # 打包后(PyInstaller)assets 在 _MEIPASS/glance/assets
    _INDEX = os.path.join(getattr(sys, "_MEIPASS", _HERE), "glance", "assets", "index.html")

_MUTEX_NAME = "Glance_SingleInstance_Mutex_v2"
_EVENT_NAME = "Glance_Show_Event_v2"

_kernel32 = ctypes.windll.kernel32
_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0x00000000
_WAIT_FAILED = 0xFFFFFFFF

# 64 位下必须设 restype,否则返回的句柄被截断成无效值(会引发忙等死循环、UI 假死)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.SetEvent.restype = wintypes.BOOL
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetLastError.restype = wintypes.DWORD


class App:
    def __init__(self, start_hidden):
        # 注意:对象型属性必须以 _ 开头,否则 pywebview 的 js_api 生成会递归遍历
        # Window/NativeWindow 对象图而卡死(util.get_functions 跳过 _ 前缀属性)。
        self._start_hidden = start_hidden
        self._window = None
        self._native = None
        self._hotkey = None
        self._tray = None
        self._really_quit = False
        self._show_event = None
        self._stop_event = threading.Event()
        self._loaded_once = False

    # ================= Api(暴露给 JS) =================
    # ---- 搜索与动作 ----
    def status(self):
        return {"available": everything.is_available(),
                "ready": everything.is_ready()}

    def search(self, query, scope=""):
        try:
            res = everything.search(query, limit=60, scope_dir=(scope or None))
            return {"ok": True, "results": res}
        except everything.EverythingError as e:
            return {"ok": False, "error": str(e), "results": []}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": f"搜索出错:{e}", "results": []}

    def open_file(self, path):
        try:
            frecency.record(path)
            os.startfile(os.path.normpath(path))  # type: ignore[attr-defined]
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def reveal_in_folder(self, path):
        try:
            frecency.record(path)
            subprocess.Popen(["explorer.exe", f"/select,{os.path.normpath(path)}"])
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def copy_path(self, path):
        try:
            import pyperclip
            pyperclip.copy(os.path.normpath(path))
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def copy_name(self, path):
        """复制文件名(含扩展名)。"""
        try:
            import pyperclip
            pyperclip.copy(os.path.basename(os.path.normpath(path)))
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    # ---- 主题 ----
    def get_boot(self):
        return {"theme": settings.load().get("theme")}

    def set_theme(self, theme):
        if theme in ("light", "dark"):
            settings.save({"theme": theme})
        return {"ok": True}

    def set_native_dark(self, is_dark):
        try:
            if self._native:
                set_immersive_dark(self._native.hwnd(), bool(is_dark))
        except Exception:
            pass
        return {"ok": True}

    # ---- 窗口控制 ----
    def win_drag(self):
        if self._native:
            self._native.native_drag()
        return {"ok": True}

    def win_resize(self, edge):
        if self._native:
            self._native.native_resize(edge)
        return {"ok": True}

    def win_toggle_maximize(self):
        if self._native:
            self._native.toggle_maximize()
        return {"ok": True}

    def win_minimize(self):
        if self._native:
            self._native.minimize()
        return {"ok": True}

    def win_is_maximized(self):
        return bool(self._native and self._native.is_maximized())

    def win_set_height(self, h):
        """前端按内容自适应高度时调用(物理像素)。"""
        if self._native:
            self._native.set_height(h)
        return {"ok": True}

    def win_close(self):
        """关闭按钮 = 隐藏到托盘(进程常驻)。"""
        if self._native:
            self._native.hide()
        return {"ok": True}

    def save_size(self, w, h):
        # 高度按内容自适应,只持久化宽度。
        try:
            settings.save({"win_w": int(w)})
        except Exception:
            pass
        return {"ok": True}

    # ================= 生命周期 =================
    def summon(self):
        """呼出:立即显示并聚焦(空范围),前台目录在后台异步解析后再推送范围。

        目录解析走 Shell COM(相对慢),放后台线程,避免拖慢唤出 —— 先抓前台
        句柄(极快、无 COM),立刻显示窗口,范围一会儿再补上。
        """
        hwnd = None
        try:
            from . import focus
            hwnd = focus.foreground_explorer_hwnd()  # 极快,无 COM
        except Exception:
            hwnd = None
        if self._native:
            self._native.show_front()
        self._eval_js("window.__glanceShow && window.__glanceShow(%s)" % json.dumps(""))
        if hwnd:
            threading.Thread(target=self._resolve_scope, args=(hwnd,),
                             daemon=True, name="GlanceScope").start()

    def _resolve_scope(self, hwnd):
        """后台线程:COM 解析前台目录,完成后推送范围到前端。"""
        folder = ""
        try:
            from . import focus
            folder = focus.explorer_folder_for(hwnd) or ""
        except Exception:
            folder = ""
        if folder:
            self._eval_js("window.__glanceScope && window.__glanceScope(%s)" % json.dumps(folder))

    def _eval_js(self, code):
        try:
            if self._window:
                self._window.evaluate_js(code)
        except Exception:
            pass

    def quit(self):
        self._really_quit = True
        self._stop_event.set()
        try:
            if self._show_event:
                _kernel32.SetEvent(self._show_event)
        except Exception:
            pass
        try:
            if self._hotkey:
                self._hotkey.stop()
        except Exception:
            pass
        try:
            if self._tray:
                self._tray.stop()
        except Exception:
            pass
        try:
            everything.shutdown()
        except Exception:
            pass
        try:
            if self._window and self._native:
                self._native.ui_invoke(self._window.destroy)
        except Exception:
            pass

    def _on_closing(self):
        """Alt+F4 / 系统关闭 → 隐藏到托盘,除非真正退出。"""
        if self._really_quit:
            return True
        if self._native:
            self._native.hide()
        return False

    def _on_shown(self):
        if self._native:
            self._native.install()

    def _on_loaded(self):
        """页面 + WebView2 预热完成(见 run 的屏幕外预热):
        托盘启动则隐藏到托盘;手动启动则居中显示。只处理首次加载。"""
        if self._loaded_once:
            return
        self._loaded_once = True
        if not self._native:
            return
        if self._start_hidden:
            self._native.hide()
        else:
            self._native.show_front()

    def _show_event_waiter(self):
        """等待"第二次启动"的信号 → 呼出已有窗口。"""
        if not self._show_event:
            return
        while not self._really_quit:
            r = _kernel32.WaitForSingleObject(self._show_event, 0xFFFFFFFF)  # INFINITE
            if self._really_quit:
                break
            if r == _WAIT_OBJECT_0:
                self.summon()
            elif r == _WAIT_FAILED:
                time.sleep(0.5)  # 兜底:句柄异常也绝不忙等

    def _notify_backend(self, ready):
        try:
            if self._window:
                self._window.evaluate_js(
                    "window.__glanceBackend && window.__glanceBackend(%s)"
                    % ("true" if ready else "false"))
        except Exception:
            pass

    def _backend_supervisor(self):
        """持续守护内置索引；被结束后自动拉起，建库完成后通知前端。"""
        previous = None
        while not self._stop_event.is_set():
            try:
                ready = everything.ensure_running(timeout=10.0)
            except Exception:
                ready = False
            if ready != previous:
                self._notify_backend(ready)
                previous = ready
            self._stop_event.wait(2.0 if ready else 1.0)

    def _on_start(self, *_):
        """GUI 循环起来后:装热键 + 托盘 + 单实例等待 + 后台守护索引。"""
        from .hotkey import HotkeyThread
        from .tray import Tray
        self._hotkey = HotkeyThread(self.summon)
        self._hotkey.start()
        self._tray = Tray(on_show=self.summon, on_quit=self.quit)
        self._tray.run_detached()
        threading.Thread(target=self._show_event_waiter, daemon=True,
                         name="GlanceShowWaiter").start()
        threading.Thread(target=self._backend_supervisor, daemon=True,
                         name="GlanceIndexSupervisor").start()

    def run(self):
        prefs = settings.load()
        # 冷启动预热:始终把窗口创建为"可见但置于屏幕外",强制 WebView2 立刻初始化
        # 并加载页面;页面就绪(loaded 事件)后,托盘模式隐藏、手动模式居中显示。
        # 若按 hidden=True 创建,WebView2 会推迟到首次唤出才初始化 —— 表现为首次
        # 唤出慢 1~2s,且此时页面 JS 尚未就绪,__glanceShow/__glanceScope 被跳过
        # (范围抓取失效,退回全局)。预热后首次唤出即"温"的:又快、范围又准。
        self._window = webview.create_window(
            "Glance",
            url=_INDEX,
            js_api=self,
            x=-32000, y=-32000,  # 屏幕外预热,避免可见闪烁
            # 高度按内容自适应(空时仅一条搜索栏),起始给个紧凑值避免首帧过高。
            width=prefs.get("win_w", 720), height=152,
            frameless=True,
            easy_drag=False,
            on_top=True,
            background_color="#FFFFFF",
            min_size=(460, 120),
            hidden=False,
        )
        self._native = NativeWindow(self._window)
        self._window.events.shown += self._on_shown
        self._window.events.loaded += self._on_loaded
        self._window.events.closing += self._on_closing
        webview.start(self._on_start, gui="edgechromium")


def _create_named_event():
    # 自动重置、初始无信号
    h = _kernel32.CreateEventW(None, False, False, _EVENT_NAME)
    return h


def _signal_existing_and_exit():
    h = _create_named_event()
    if h:
        _kernel32.SetEvent(h)
        _kernel32.CloseHandle(h)


def main():
    start_hidden = ("--tray" in sys.argv) or ("--hidden" in sys.argv)

    # 单实例:已存在则通知其显示并退出
    mutex = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if _kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        _signal_existing_and_exit()
        return

    # 索引的拉起与等待放到 GUI 起来后的后台守护线程,
    # 不阻塞窗口首屏 —— 见 App._on_start。
    app = App(start_hidden)
    app._show_event = _create_named_event()
    app.run()
    # 退出清理
    try:
        if mutex:
            _kernel32.CloseHandle(mutex)
    except Exception:
        pass


if __name__ == "__main__":
    main()
