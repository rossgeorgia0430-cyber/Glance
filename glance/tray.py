# -*- coding: utf-8 -*-
"""系统托盘(pystray):左键/显示、退出。"""
import os
import threading

import pystray
from PIL import Image


def _load_icon():
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "assets", "icon.ico"),):
        if os.path.exists(p):
            try:
                return Image.open(p)
            except Exception:
                pass
    return Image.new("RGB", (64, 64), (47, 109, 246))  # 兜底:浅蓝方块


class Tray:
    def __init__(self, on_show, on_quit):
        self._icon = pystray.Icon(
            "Glance", _load_icon(), "Glance —— 文件搜索",
            menu=pystray.Menu(
                pystray.MenuItem("显示 (Ctrl+Alt+S)", lambda i, it: on_show(), default=True),
                pystray.MenuItem("退出", lambda i, it: on_quit()),
            ),
        )

    def run_detached(self):
        threading.Thread(target=self._icon.run, daemon=True, name="GlanceTray").start()

    def stop(self):
        try:
            self._icon.stop()
        except Exception:
            pass
