# -*- coding: utf-8 -*-
"""热键 UI 指令桥的无 GUI 回归测试。"""
import json
import time
import unittest
from unittest.mock import patch

from glance.app import App


class _Window:
    def __init__(self):
        self.calls = []

    def evaluate_js(self, code):
        self.calls.append(code)


class _Native:
    @staticmethod
    def ui_invoke(fn):
        fn()


def _ready_app():
    app = App(start_hidden=True)
    app._window = _Window()
    app._native = _Native()
    return app


def _wait_for_calls(app, count):
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if len(app._window.calls) >= count:
            return
        time.sleep(0.01)
    raise AssertionError(f"Expected {count} JavaScript calls, got {app._window.calls!r}")


class UiBridgeTests(unittest.TestCase):
    def test_commands_queue_until_frontend_handshake(self):
        app = _ready_app()

        app._eval_js("first()")
        self.assertEqual(app._window.calls, [])

        app.ui_ready()
        app._eval_js("second()")
        _wait_for_calls(app, 2)
        self.assertEqual(app._window.calls, ["first()", "second()"])

    def test_stale_scope_resolution_cannot_override_new_summon(self):
        app = _ready_app()
        app.ui_ready()
        app._summon_id = 2

        with patch("glance.focus.explorer_folder_for", return_value=r"C:\Focused"):
            app._resolve_scope(100, summon_id=1)
            app._resolve_scope(100, summon_id=2)

        _wait_for_calls(app, 1)
        self.assertEqual(
            app._window.calls,
            ["window.__glanceScope && window.__glanceScope(%s)" % json.dumps(r"C:\Focused")],
        )


if __name__ == "__main__":
    unittest.main()
