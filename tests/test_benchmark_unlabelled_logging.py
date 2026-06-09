import unittest

from main import benchmark_label_for_logging


class BenchmarkUnlabelledLoggingTests(unittest.TestCase):
    def test_unlabelled_live_frames_are_logged_as_none(self):
        self.assertEqual(benchmark_label_for_logging(None), "none")

    def test_protocol_label_is_preserved(self):
        self.assertEqual(benchmark_label_for_logging("center_hold"), "center_hold")


if __name__ == "__main__":
    unittest.main()
