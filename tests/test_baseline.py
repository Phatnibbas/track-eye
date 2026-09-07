import unittest
from pathlib import Path

from track_eye.baseline import BaselineSession


class BaselineSessionTests(unittest.TestCase):
    def test_start_request_enters_face_ready_state(self):
        session = BaselineSession(Path("benchmark_data-test"))
        self.assertEqual(session.status()["state"], "idle")
        session.request_start()
        status = session.status()
        self.assertEqual(status["state"], "ready")
        self.assertTrue(status["start_requested"])
        self.assertFalse(status["face_ready"])


if __name__ == "__main__":
    unittest.main()
