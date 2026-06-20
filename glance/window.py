# -*- coding: utf-8 -*-
"""
Win32 原生窗口行为 —— 给 frameless pywebview 窗口加回全部 Win10/11 原生能力。

改编自 Inkwell(inkwell/app.py):
- WM_NCCALCSIZE→0 子类化(客户区铺满,无系统缩放边)+ 永久 WS_THICKFRAME|WS_MAXIMIZEBOX
  (原生 8 向缩放 + Aero Snap + 任务栏/系统菜单)。
- 拖动/缩放经 ReleaseCapture + SendMessage(WM_NCLBUTTONDOWN)。
- 最大化用 MaximizedBounds 修正高 DPI/多屏工作区。
- DWM 圆角/边框/沉浸暗色。
- 常驻显示/隐藏 + 抢前台(供全局热键呼出)。
所有 Win32 调用经 window.native.BeginInvoke 投到 UI 线程(SendMessage 模态循环会卡事件循环)。
"""
import ctypes
from ctypes import wintypes

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_dwmapi = ctypes.windll.dwmapi

# --- 常量 ------------------------------------------------------------------
_WM_NCLBUTTONDOWN = 0x00A1
_WM_NCCALCSIZE = 0x0083
_GWL_STYLE = -16
_GWLP_WNDPROC = -4
_HTCAPTION = 2
_WS_THICKFRAME = 0x00040000
_WS_MAXIMIZEBOX = 0x00010000
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_SW_RESTORE = 9

_RESIZE_HT = {
    'left': 10, 'right': 11, 'top': 12, 'topleft': 13, 'topright': 14,
    'bottom': 15, 'bottomleft': 16, 'bottomright': 17,
}

_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_BORDER_COLOR = 34
_DWMWCP_DEFAULT = 0
_DWMWCP_DONOTROUND = 1
_DWMWA_COLOR_DEFAULT = 0xFFFFFFFF
_DWMWA_COLOR_NONE = 0xFFFFFFFE

# 64 位用 *Ptr 变体,避免 WS 样式(含 0x80000000)有符号溢出
if ctypes.sizeof(ctypes.c_void_p) == 8:
    _GetWL, _SetWL = _user32.GetWindowLongPtrW, _user32.SetWindowLongPtrW
    _GetWL.argtypes = [wintypes.HWND, ctypes.c_int]; _GetWL.restype = ctypes.c_ssize_t
    _SetWL.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]; _SetWL.restype = ctypes.c_ssize_t
else:
    _GetWL, _SetWL = _user32.GetWindowLongW, _user32.SetWindowLongW
    _GetWL.argtypes = [wintypes.HWND, ctypes.c_int]; _GetWL.restype = wintypes.LONG
    _SetWL.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]; _SetWL.restype = wintypes.LONG

_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                              ctypes.c_size_t, ctypes.c_ssize_t)
_user32.CallWindowProcW.restype = ctypes.c_ssize_t
_user32.CallWindowProcW.argtypes = [ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                    ctypes.c_size_t, ctypes.c_ssize_t]
_user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
# 64 位下句柄/线程相关调用必须设 restype/argtypes,避免指针截断
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.BringWindowToTop.argtypes = [wintypes.HWND]
_user32.SetActiveWindow.argtypes = [wintypes.HWND]
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
_user32.AttachThreadInput.restype = wintypes.BOOL
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_WNDPROC_REFS = []  # 防回调被 GC


def _center(hwnd):
    """主屏水平居中、靠上(物理像素,规避高 DPI 错位)。"""
    try:
        rect = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        sw, sh = _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)
        _user32.SetWindowPos(hwnd, 0, max(0, (sw - w) // 2), max(0, int(sh * 0.16)),
                             0, 0, _SWP_NOSIZE | _SWP_NOZORDER)
    except Exception:
        pass


def _apply_style(hwnd, style):
    if _GetWL(hwnd, _GWL_STYLE) == style:
        return
    _SetWL(hwnd, _GWL_STYLE, style)
    _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                         _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED)


def _install_native_chrome(hwnd):
    old = [0]

    @_WNDPROC
    def proc(h, msg, wp, lp):
        if msg == _WM_NCCALCSIZE and wp:
            return 0
        return _user32.CallWindowProcW(old[0], h, msg, wp, lp)

    old[0] = _SetWL(hwnd, _GWLP_WNDPROC, ctypes.cast(proc, ctypes.c_void_p).value)
    _WNDPROC_REFS.append(proc)
    _apply_style(hwnd, _GetWL(hwnd, _GWL_STYLE) | _WS_THICKFRAME | _WS_MAXIMIZEBOX)


def _dwm_set(hwnd, attr, value):
    try:
        f = _dwmapi.DwmSetWindowAttribute
        f.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        f.restype = ctypes.c_long
        f(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def set_frame_visual(hwnd, maximized):
    """最大化时去圆角/去边框,还原时恢复系统默认。"""
    _dwm_set(hwnd, _DWMWA_WINDOW_CORNER_PREFERENCE,
             ctypes.c_int(_DWMWCP_DONOTROUND if maximized else _DWMWCP_DEFAULT))
    _dwm_set(hwnd, _DWMWA_BORDER_COLOR,
             ctypes.c_uint32(_DWMWA_COLOR_NONE if maximized else _DWMWA_COLOR_DEFAULT))


def set_immersive_dark(hwnd, dark):
    """让窗口 DWM 细边/阴影跟随暗色。"""
    _dwm_set(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.c_int(1 if dark else 0))


def _restore_and_foreground(hwnd):
    """把窗口拉到前台并取得输入焦点(绕过 Windows 抢焦点限制)。"""
    _user32.ShowWindow(hwnd, _SW_RESTORE)
    fg = _user32.GetForegroundWindow()
    if fg and fg != hwnd:
        cur = _kernel32.GetCurrentThreadId()
        fgt = _user32.GetWindowThreadProcessId(fg, None)
        attached = False
        try:
            attached = bool(_user32.AttachThreadInput(fgt, cur, True))
            _user32.BringWindowToTop(hwnd)
            _user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                _user32.AttachThreadInput(fgt, cur, False)
    else:
        _user32.SetForegroundWindow(hwnd)
    _user32.SetActiveWindow(hwnd)


class NativeWindow:
    """包住 pywebview window,提供原生窗口行为与常驻显示/隐藏。"""

    def __init__(self, window):
        self._w = window
        self._installed = False
        self._normal_size = None

    # ---- 基础 ----
    def hwnd(self):
        return int(self._w.native.Handle.ToInt32())

    def ui_invoke(self, fn):
        try:
            from System import Action
            self._w.native.BeginInvoke(Action(fn))
        except Exception:
            try:
                fn()
            except Exception:
                pass

    def install(self):
        """窗口显示后一次性装原生 chrome。"""
        def fn():
            if not self._installed:
                _install_native_chrome(self.hwnd())
                self._installed = True
            self.apply_maximized_bounds()
        self.ui_invoke(fn)

    def apply_maximized_bounds(self):
        try:
            from System.Windows.Forms import Screen
            from System.Drawing import Rectangle
            form = self._w.native
            wa = Screen.FromControl(form).WorkingArea
            form.MaximizedBounds = Rectangle(wa.X, wa.Y, wa.Width, wa.Height)
        except Exception:
            pass

    def is_maximized(self):
        try:
            return bool(_user32.IsZoomed(self.hwnd()))
        except Exception:
            return False

    # ---- 拖动 / 缩放 / 最大化 / 最小化 ----
    def native_drag(self):
        hwnd = self.hwnd()

        def fn():
            _user32.ReleaseCapture()
            _user32.SendMessageW(hwnd, _WM_NCLBUTTONDOWN, _HTCAPTION, 0)

        self.ui_invoke(fn)

    def native_resize(self, edge):
        code = _RESIZE_HT.get(edge)
        if code is None:
            return
        hwnd = self.hwnd()

        def fn():
            _user32.ReleaseCapture()
            _user32.SendMessageW(hwnd, _WM_NCLBUTTONDOWN, code, 0)

        self.ui_invoke(fn)

    def toggle_maximize(self):
        def fn():
            try:
                from System.Windows.Forms import FormWindowState
                from System.Drawing import Size
                form = self._w.native
                if form.WindowState == FormWindowState.Maximized:
                    form.WindowState = FormWindowState.Normal
                    if self._normal_size:
                        form.Size = Size(*self._normal_size)
                else:
                    self._normal_size = (form.Width, form.Height)
                    self.apply_maximized_bounds()
                    form.WindowState = FormWindowState.Maximized
                set_frame_visual(self.hwnd(), self.is_maximized())
            except Exception:
                pass

        self.ui_invoke(fn)

    def set_height(self, h_physical):
        """按内容自适应窗口高度(物理像素,左上角锚定向下生长)。最大化时忽略。"""
        try:
            h = int(h_physical)
        except Exception:
            return
        if h < 80:
            h = 80
        if self.is_maximized():
            return

        def fn():
            try:
                hwnd = self.hwnd()
                rect = wintypes.RECT()
                _user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                hh = min(h, _user32.GetSystemMetrics(1))  # 不超过屏幕高
                if hh == rect.bottom - rect.top:
                    return  # 高度未变,免触发多余 resize
                _user32.SetWindowPos(hwnd, 0, 0, 0, w, hh,
                                     _SWP_NOMOVE | _SWP_NOZORDER | _SWP_NOACTIVATE)
            except Exception:
                pass

        self.ui_invoke(fn)

    def minimize(self):
        try:
            self._w.minimize()
        except Exception:
            pass

    # ---- 常驻显示 / 隐藏 ----
    def hide(self):
        try:
            self.ui_invoke(lambda: self._w.hide())
        except Exception:
            pass

    def show_front(self):
        def fn():
            try:
                self._w.show()
            except Exception:
                pass
            try:
                hwnd = self.hwnd()
                if not self.is_maximized():
                    _center(hwnd)
                _restore_and_foreground(hwnd)
            except Exception:
                pass
        self.ui_invoke(fn)
