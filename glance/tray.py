# -*- coding: utf-8 -*-
"""系统托盘(pystray):左键/显示、退出。"""
import os
import threading

import pystray
from PIL import Image

_ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")


class Tray:
    def __init__(self, on_show, on_quit):
        self._icon = pystray.Icon(
            "Glance", Image.open(_ICON), "Glance —— 文件搜索",
            menu=pystray.Menu(
                pystray.MenuItem("显示 (Ctrl+Alt+S)", lambda i, it: on_show(), default=True),
                pystray.MenuItem("退出", lambda i, it: on_quit()),
            ),
        )

    def run_detached(self):
        threading.Thread(target=self._icon.run, daemon=True, name="GlanceTray").start()

    def stop(self):
        self._icon.stop()
