import unittest
from unittest import mock

from glance import everything


class SearchRecoveryTests(unittest.TestCase):
    def test_ipc_disconnect_recovers_and_retries_complete_query(self):
        hit = {"name": "Glance.exe", "path": r"C:\Glance.exe", "dir": "C:\\",
               "is_dir": False, "ext": "exe", "size": 1, "mtime": 0.0}
        with mock.patch.object(everything, "is_ready", return_value=True), \
                mock.patch.object(everything, "_load", return_value=object()), \
                mock.patch.object(everything, "ensure_running", return_value=True) as recover, \
                mock.patch.object(everything, "_run", side_effect=[
                    everything.EverythingDisconnectedError("disconnected"), [hit], [hit]
                ]) as run:
            results = everything.search("glance", limit=10)

        self.assertEqual([hit], results)
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


if __name__ == "__main__":
    unittest.main()
