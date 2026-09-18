import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from win32com.client import dynamic

from glance import focus

TOP_HWND = 0x100


def _shell_window(path, tab):
    folder = SimpleNamespace(Self=SimpleNamespace(Path=path))
    return SimpleNamespace(HWND=TOP_HWND, Document=SimpleNamespace(Folder=folder), tab=tab)


class ExplorerTabTests(unittest.TestCase):
    def test_tabs_sharing_one_window_resolve_to_active_tab(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            windows = [_shell_window(first, tab=0x201), _shell_window(second, tab=0x202)]
            shell_app = SimpleNamespace(Windows=lambda: windows)
            with mock.patch.object(focus.win32gui, "FindWindowEx", return_value=0x202), \
                    mock.patch.object(focus, "_tab_window", side_effect=lambda w: w.tab), \
                    mock.patch.object(dynamic, "Dispatch", return_value=shell_app):
                self.assertEqual(second, focus.explorer_folder_for(TOP_HWND))


if __name__ == "__main__":
    unittest.main()
