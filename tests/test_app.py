import unittest
from unittest import mock

from glance import app, everything


class SearchApiTests(unittest.TestCase):
    def test_older_request_becomes_stale_once_newer_arrives(self):
        captured = []

        def fake_search(query, limit, scope_dir, is_stale):
            captured.append(is_stale)
            return []

        api = app.App(start_hidden=False, show_event=None)
        with mock.patch.object(everything, "search", side_effect=fake_search):
            api.search("gl")
            self.assertFalse(captured[0]())
            api.search("glance")

        self.assertTrue(captured[0]())
        self.assertFalse(captured[1]())

    def test_superseded_search_reports_stale(self):
        api = app.App(start_hidden=False, show_event=None)
        with mock.patch.object(everything, "search", side_effect=everything.SearchSuperseded()):
            self.assertEqual({"ok": True, "stale": True, "results": []}, api.search("glance"))

    def test_scope_is_forwarded_and_empty_scope_means_global(self):
        api = app.App(start_hidden=False, show_event=None)
        with mock.patch.object(everything, "search", return_value=[]) as search:
            api.search("glance", "D:\\Projects")
            api.search("glance", "")

        self.assertEqual("D:\\Projects", search.call_args_list[0].kwargs["scope_dir"])
        self.assertIsNone(search.call_args_list[1].kwargs["scope_dir"])


if __name__ == "__main__":
    unittest.main()
