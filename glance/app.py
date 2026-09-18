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
import logging
import os
import subprocess
import sys
import threading
from ctypes import wintypes
from logging.handlers import RotatingFileHandler

import webview

from . import everything, frecency, settings
from .window import NativeWindow, set_immersive_dark
# 注意:focus / hotkey / tray / pyperclip 均延迟导入(见下),
# 避免在显示窗口前就加载 win32com / pystray / PIL,拖慢启动。

log = logging.getLogger(__name__)

_INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "index.html")

_MUTEX_NAME = "Glance_SingleInstance_Mutex_v2"
_EVENT_NAME = "Glance_Show_Event_v2"
_LOG_MAX_BYTES = 512 * 1024

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0x00000000
_INFINITE = 0xFFFFFFFF

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


def _run_file_action(action, path):
    """对结果文件执行打开/定位;成功后计入 frecency,失败原因回给前端提示。"""
    path = os.path.normpath(path)
    try:
        action(path)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    frecency.record(path)
    return {"ok": True}


def _copy_text(text):
    import pyperclip
    try:
        pyperclip.copy(text)
    except pyperclip.PyperclipException as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


class App:
    def __init__(self, start_hidden, show_event):
        # 注意:对象型属性必须以 _ 开头,否则 pywebview 的 js_api 生成会递归遍历
        # Window/NativeWindow 对象图而卡死(util.get_functions 跳过 _ 前缀属性)。
        self._start_hidden = start_hidden
        self._show_event = show_event
        self._window = None
        self._native = None
        self._hotkey = None
        self._tray = None
        self._really_quit = False
        self._stop_event = threading.Event()
        self._loaded_once = False
        self._summoned_early = False
        self._summon_generation = 0
        self._summon_lock = threading.Lock()
        self._search_seq = 0
        self._search_lock = threading.Lock()

    # ================= Api(暴露给 JS) =================
    # ---- 搜索与动作 ----
    def status(self):
        return {"ready": everything.is_ready()}

    def search(self, query, scope=""):
        # pywebview 每次 JS 调用都开一个线程;单次查询要几百毫秒,打字时旧查询会在
        # 索引锁上排队。按到达顺序编号,轮到执行时已有更新的查询就直接让位。
        with self._search_lock:
            self._search_seq += 1
            seq = self._search_seq
        try:
            results = everything.search(query, limit=60, scope_dir=(scope or None),
                                        is_stale=lambda: seq != self._search_seq)
        except everything.SearchSuperseded:
            return {"ok": True, "stale": True, "results": []}
        except everything.EverythingError as e:
            return {"ok": False, "error": str(e), "results": []}
        except Exception as e:  # noqa: BLE001  JS 边界:未预期的错误也要回给前端显示
            log.exception("搜索出错")
            return {"ok": False, "error": f"搜索出错:{e}", "results": []}
        return {"ok": True, "results": results}

    def open_file(self, path):
        return _run_file_action(os.startfile, path)  # type: ignore[attr-defined]

    def reveal_in_folder(self, path):
        return _run_file_action(
            lambda p: subprocess.Popen(["explorer.exe", f"/select,{p}"]), path)

    def copy_path(self, path):
        return _copy_text(os.path.normpath(path))

    def copy_name(self, path):
        """复制文件名(含扩展名)。"""
        return _copy_text(os.path.basename(os.path.normpath(path)))

    # ---- 主题 ----
    def get_boot(self):
        return {"theme": settings.load()["theme"]}

    def set_theme(self, theme):
        if theme in ("light", "dark"):
            settings.save({"theme": theme})

    def set_native_dark(self, is_dark):
        set_immersive_dark(self._native.hwnd(), bool(is_dark))

    # ---- 窗口控制 ----
    def win_drag(self):
        self._native.native_drag()

    def win_resize(self, edge):
        self._native.native_resize(edge)

    def win_toggle_maximize(self):
        self._native.toggle_maximize()

    def win_minimize(self):
        self._native.minimize()

    def win_is_maximized(self):
        return self._native.is_maximized()

    def win_set_height(self, h):
        """前端按内容自适应高度时调用(物理像素)。"""
        self._native.set_height(h)

    def win_close(self):
        """关闭按钮 = 隐藏到托盘(进程常驻)。"""
        self._native.hide()

    def save_size(self, w):
        """记住窗口宽度(逻辑像素,即 create_window 的 width 单位)。"""
        settings.save({"win_w": int(w)})

    # ================= 生命周期 =================
    def summon(self):
        """呼出:立即显示并聚焦(空范围),前台目录在后台异步解析后再推送范围。

        目录解析走 Shell COM(相对慢),放后台线程,避免拖慢唤出 —— 先抓前台
        句柄(极快、无 COM),立刻显示窗口,范围一会儿再补上。
        """
        from . import focus
        self._summoned_early = True
        # Hotkey、托盘和单实例事件都可能从不同线程同时呼出。给每次呼出编号，
        # 防止较慢的旧 Explorer COM 查询晚到后覆盖最新一次的搜索范围。
        with self._summon_lock:
            self._summon_generation += 1
            generation = self._summon_generation
        hwnd = focus.foreground_explorer_hwnd()
        self._native.show_front()
        self._eval_js("window.__glanceShow && window.__glanceShow()")
        if hwnd:
            threading.Thread(target=self._resolve_scope, args=(hwnd, generation),
                             daemon=True, name="GlanceScope").start()

    def _resolve_scope(self, hwnd, generation):
        """后台线程:COM 解析前台目录,完成后推送范围到前端。"""
        from . import focus
        folder = focus.explorer_folder_for(hwnd)
        with self._summon_lock:
            is_latest = generation == self._summon_generation
        if folder and is_latest:
            self._eval_js("window.__glanceScope && window.__glanceScope(%s)" % json.dumps(folder))

    def _eval_js(self, code):
        """向页面推送通知。调用方是热键/托盘/守护线程,一次推送失败不能打断它们。"""
        try:
            self._window.evaluate_js(code)
        except Exception:  # noqa: BLE001
            log.warning("推送到页面失败:%s", code, exc_info=True)

    def quit(self):
        self._really_quit = True
        self._stop_event.set()
        if self._show_event:
            _kernel32.SetEvent(self._show_event)  # 唤醒 _show_event_waiter 让它退出
        try:
            self._hotkey.stop()
            self._tray.stop()
            everything.shutdown()
        finally:
            # 前面的清理即使失败也必须销毁窗口,否则进程不会退出
            self._native.ui_invoke(self._window.destroy)

    def _on_closing(self):
        """Alt+F4 / 系统关闭 → 隐藏到托盘,除非真正退出。"""
        if self._really_quit:
            return True
        self._native.hide()
        return False

    def _on_shown(self):
        self._native.install()

    def _on_loaded(self):
        """页面 + WebView2 预热完成(见 run 的屏幕外预热):
        托盘启动则隐藏到托盘;手动启动则居中显示。只处理首次加载。"""
        if self._loaded_once:
            return
        self._loaded_once = True
        if self._start_hidden and not self._summoned_early:
            self._native.hide()
        else:
            self._native.show_front()

    def _show_event_waiter(self):
        """等待"第二次启动"的信号 → 呼出已有窗口。"""
        while not self._really_quit:
            r = _kernel32.WaitForSingleObject(self._show_event, _INFINITE)
            if r != _WAIT_OBJECT_0:
                # 句柄失效后再等也不会恢复,直接结束,避免忙等
                log.error("单实例事件等待失败 (返回 %#x, 错误码 %d)", r, ctypes.get_last_error())
                return
            if not self._really_quit:
                self.summon()

    def _backend_supervisor(self):
        """持续守护内置索引:被结束后自动拉起,状态变化时通知前端。"""
        previous = None
        while not self._stop_event.is_set():
            try:
                ready = everything.ensure_running(timeout=10.0)
            except Exception:  # noqa: BLE001  守护循环一旦退出,索引被结束后就再也不会拉起
                log.exception("守护索引进程出错")
                ready = False
            if ready != previous:
                self._eval_js("window.__glanceBackend && window.__glanceBackend(%s)"
                              % json.dumps(ready))
                previous = ready
            self._stop_event.wait(2.0 if ready else 1.0)

    def _watch_hotkey_registration(self):
        """热键注册失败时通知前端(evaluate_js 自己会等页面就绪)。"""
        if not self._hotkey.wait_registered(5.0):
            self._eval_js("window.__glanceHotkeyFailed && window.__glanceHotkeyFailed()")

    def _on_start(self):
        """GUI 循环起来后:装热键 + 托盘 + 单实例等待 + 后台守护索引。"""
        from .hotkey import HotkeyThread
        from .tray import Tray
        self._hotkey = HotkeyThread(self.summon)
        self._hotkey.start()
        self._tray = Tray(on_show=self.summon, on_quit=self.quit)
        self._tray.run_detached()
        workers = [(self._watch_hotkey_registration, "GlanceHotkeyWatcher"),
                   (self._backend_supervisor, "GlanceIndexSupervisor")]
        if self._show_event:
            workers.append((self._show_event_waiter, "GlanceShowWaiter"))
        for target, name in workers:
            threading.Thread(target=target, daemon=True, name=name).start()

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
            width=prefs["win_w"], height=152,
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


def _setup_logging():
    """警告和错误写到 %LOCALAPPDATA%\\Glance\\glance.log:打包版没有控制台,不落盘就无从排查。"""
    try:
        handler = RotatingFileHandler(settings.data_dir() / "glance.log", maxBytes=_LOG_MAX_BYTES,
                                      backupCount=1, encoding="utf-8")
    except OSError:
        return  # 日志写不了不应妨碍程序运行
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"))
    logging.basicConfig(level=logging.WARNING, handlers=[handler])
    threading.excepthook = lambda a: log.error(
        "线程 %s 未捕获异常", a.thread.name if a.thread else "?",
        exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def main():
    # 单实例:已存在则通知其显示并退出。互斥体句柄随进程退出由系统释放。
    _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    already_running = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    # 自动重置、初始无信号
    show_event = _kernel32.CreateEventW(None, False, False, _EVENT_NAME)
    if already_running:
        if show_event:
            _kernel32.SetEvent(show_event)
            _kernel32.CloseHandle(show_event)
        return

    _setup_logging()
    if not show_event:
        log.error("创建单实例事件失败 (错误码 %d),再次启动将无法呼出已有窗口",
                  ctypes.get_last_error())
    # 索引的拉起与等待放到 GUI 起来后的后台守护线程,
    # 不阻塞窗口首屏 —— 见 App._on_start。
    App(start_hidden="--tray" in sys.argv, show_event=show_event).run()


if __name__ == "__main__":
    main()
