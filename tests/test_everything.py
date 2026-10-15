import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from glance import everything

HIT = {"name": "Glance.exe", "path": r"C:\Glance.exe", "dir": "C:\\",
       "is_dir": False, "ext": "exe", "size": 1, "mtime": 0.0}


def _patched_backend(run_side_effect):
    return (mock.patch.object(everything, "is_ready", return_value=True),
            mock.patch.object(everything, "_load", return_value=object()),
            mock.patch.object(everything, "_run", side_effect=run_side_effect))


class SearchRecoveryTests(unittest.TestCase):
    def test_ipc_disconnect_recovers_and_retries_complete_query(self):
        with mock.patch.object(everything, "is_ready", return_value=True), \
                mock.patch.object(everything, "_load", return_value=object()), \
                mock.patch.object(everything, "ensure_running", return_value=True) as recover, \
                mock.patch.object(everything, "_run", side_effect=[
                    everything.EverythingDisconnectedError("disconnected"), [HIT], [HIT]
                ]) as run:
            results = everything.search("glance", limit=10)

        self.assertEqual([HIT], results)
        recover.assert_called_once_with(timeout=3.0, poll=0.15)
        self.assertEqual(3, run.call_count)

    def test_ipc_disconnect_is_retried_only_once(self):
        error = everything.EverythingDisconnectedError("disconnected")
        with mock.patch.object(everything, "is_ready", return_value=True), \
                mock.patch.object(everything, "_load", return_value=object()), \
                mock.patch.object(everything, "ensure_running", return_value=True), \
                mock.patch.object(everything, "_run", side_effect=[error, error]) as run:
            with self.assertRaises(everything.EverythingDisconnectedError):
                everything.search("glance")

        self.assertEqual(2, run.call_count)


class MatchPathTests(unittest.TestCase):
    def test_scoped_single_token_matches_file_names_only(self):
        ready, load, run = _patched_backend([[], []])
        with ready, load, run as run_mock:
            everything.search("glance", scope_dir="D:\\Projects\\Glance")

        (exact_query, exact_match_path), (fuzzy_query, fuzzy_match_path) = \
            [(c.args[1], c.kwargs["match_path"]) for c in run_mock.call_args_list]
        self.assertEqual('"D:\\Projects\\Glance\\" glance', exact_query)
        self.assertFalse(exact_match_path)
        self.assertEqual('"D:\\Projects\\Glance\\" *g*l*a*n*c*e*', fuzzy_query)
        self.assertFalse(fuzzy_match_path)

    def test_multiple_tokens_match_full_path(self):
        ready, load, run = _patched_backend([[HIT] * 30])
        with ready, load, run as run_mock:
            everything.search("glance exe")

        self.assertTrue(run_mock.call_args.kwargs["match_path"])


class SupersededTests(unittest.TestCase):
    def test_stale_query_never_reaches_index(self):
        ready, load, run = _patched_backend([])
        with ready, load, run as run_mock:
            with self.assertRaises(everything.SearchSuperseded):
                everything.search("glance", is_stale=lambda: True)

        run_mock.assert_not_called()

    def test_query_superseded_mid_way_skips_fuzzy_fallback(self):
        stale = iter([False, True])
        ready, load, run = _patched_backend([[]])
        with ready, load, run as run_mock:
            with self.assertRaises(everything.SearchSuperseded):
                everything.search("glance", is_stale=lambda: next(stale))

        self.assertEqual(1, run_mock.call_count)


class LaunchTests(unittest.TestCase):
    def test_index_database_is_kept_next_to_private_config(self):
        index_dir = Path("C:/Users/u/AppData/Local/Glance/Indexer")
        cfg = index_dir / "Everything.ini"
        with mock.patch.object(everything, "_index_dir", return_value=index_dir), \
                mock.patch.object(everything, "_ensure_config", return_value=cfg), \
                mock.patch.object(everything.subprocess, "Popen") as popen:
            everything._launch()

        args = popen.call_args.args[0]
        self.assertEqual(str(cfg.with_name("Everything.db")), args[args.index("-db") + 1])


class SaveDbTests(unittest.TestCase):
    def _save(self, db_path, clock):
        dll = mock.Mock()
        dll.Everything_SaveDB.return_value = True
        with mock.patch.object(everything, "_db_path", return_value=db_path), \
                mock.patch.object(everything, "_load", return_value=dll), \
                mock.patch.object(everything.time, "monotonic", return_value=clock):
            everything.save_db_if_due()
        return dll.Everything_SaveDB.call_count

    def setUp(self):
        patcher = mock.patch.object(everything, "_next_db_save", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "Everything.db"

    def test_missing_database_is_saved_once_per_interval(self):
        self.assertEqual(1, self._save(self.db, clock=100.0))
        self.assertEqual(0, self._save(self.db, clock=101.0))
        self.assertEqual(1, self._save(self.db, clock=100.0 + everything._DB_SAVE_INTERVAL))

    def test_recently_saved_database_waits_for_remaining_interval(self):
        self.db.write_bytes(b"")
        age = 600.0
        mtime = time.time() - age
        os.utime(self.db, (mtime, mtime))

        self.assertEqual(0, self._save(self.db, clock=100.0))
        self.assertAlmostEqual(100.0 + everything._DB_SAVE_INTERVAL - age,
                               everything._next_db_save, delta=5.0)


class ForcedConfigTests(unittest.TestCase):
    def test_rewrites_forced_keys_and_keeps_everything_else(self):
        lines = ["[Everything]", "show_tray_icon=1", "index_size=1", "IPC = 0"]
        patched = everything._apply_forced_config(lines)

        self.assertIn("show_tray_icon=0", patched)
        self.assertIn("ipc=1", patched)
        self.assertIn("index_size=1", patched)
        for key, value in everything._FORCED_CONFIG.items():
            self.assertEqual(1, patched.count(f"{key}={value}"))

    def test_adds_missing_section_header(self):
        patched = everything._apply_forced_config(["index_size=1"])
        self.assertEqual("[Everything]", patched[0])


if __name__ == "__main__":
    unittest.main()
