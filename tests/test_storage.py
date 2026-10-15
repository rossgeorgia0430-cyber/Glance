import json
import os
import tempfile
import time
import unittest
from unittest import mock

from glance import frecency, settings


class _TempDataDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"LOCALAPPDATA": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        settings.data_dir.cache_clear()
        self.addCleanup(settings.data_dir.cache_clear)
        frecency._cache = None
        self.addCleanup(setattr, frecency, "_cache", None)


class SettingsTests(_TempDataDir):
    def test_round_trip_keeps_only_known_keys(self):
        settings.save({"theme": "dark", "win_w": 900, "unknown": 1})

        self.assertEqual({"theme": "dark", "win_w": 900}, settings.load())

    def test_out_of_range_width_falls_back_to_default(self):
        path = settings.data_dir() / "settings.json"
        path.write_text(json.dumps({"win_w": 10, "theme": "blue"}), encoding="utf-8")

        self.assertEqual(settings._DEFAULTS, settings.load())

    def test_corrupt_file_falls_back_to_defaults(self):
        (settings.data_dir() / "settings.json").write_text("{", encoding="utf-8")

        with self.assertLogs("glance.settings", "WARNING"):
            self.assertEqual(settings._DEFAULTS, settings.load())


class FrecencyTests(_TempDataDir):
    def test_recorded_path_is_boosted_case_insensitively(self):
        now = time.time()
        self.assertEqual(0.0, frecency.boost(r"C:\Docs\a.txt", now))

        frecency.record(r"C:\Docs\a.txt")

        self.assertGreater(frecency.boost(r"c:\docs\A.TXT", now), 0.0)
        frecency._cache = None  # 强制从磁盘重新读取
        self.assertGreater(frecency.boost(r"C:\Docs\a.txt", now), 0.0)

    def test_prunes_to_most_recent_entries(self):
        with mock.patch.object(frecency, "_PRUNE_AT", 3), mock.patch.object(frecency, "_KEEP", 2), \
                mock.patch.object(frecency.time, "time", side_effect=[1.0, 2.0, 3.0, 4.0]):
            for name in "abcd":
                frecency.record(f"C:\\{name}.txt")

        self.assertEqual({r"c:\c.txt", r"c:\d.txt"}, set(frecency._load()))


if __name__ == "__main__":
    unittest.main()
