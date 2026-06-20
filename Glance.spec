# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(SPECPATH)
ICON = os.path.join("glance", "assets", "icon.ico")

datas = [
    (os.path.join("glance", "assets"), os.path.join("glance", "assets")),
    (os.path.join("glance", "GlanceIndex64.dll"), "glance"),
    # 专属命名索引后端：无搜索窗口、无托盘，不连接用户的默认 Everything 实例。
    (os.path.join("glance", "bin", "GlanceIndexer.exe"), os.path.join("glance", "bin")),
    ("THIRD_PARTY_NOTICES.txt", "."),
]
binaries = []
hiddenimports = [
    "webview", "webview.platforms.edgechromium", "webview.platforms.winforms",
    "clr", "clr_loader", "clr_loader.netfx", "pythonnet",
    "bottle", "proxy_tools", "typing_extensions",
    "rapidfuzz", "pyperclip",
    "pystray", "pystray._win32", "PIL", "PIL.Image",
    "win32com", "win32com.client", "win32gui", "win32api", "win32con",
    "pythoncom", "pywintypes",
]
for pkg in ("webview", "pystray"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["run_glance.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy",
        "cefpython3", "gi", "cocoa",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Glance",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON if os.path.exists(ICON) else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Glance",
)
