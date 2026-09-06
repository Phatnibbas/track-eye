import unittest

import numpy as np

from track_eye.web import FrameHub


class FrameHubTests(unittest.TestCase):
    def test_wait_next_returns_each_new_sequence_once(self):
        hub = FrameHub()
        self.assertIsNone(hub.wait_next(0, timeout=0.001))
        first = hub.update(np.zeros((8, 8, 3), dtype=np.uint8))
        second = hub.update(np.full((8, 8, 3), 255, dtype=np.uint8))
        self.assertEqual((first, second), (1, 2))
        sequence, jpeg = hub.wait_next(0, timeout=0.1)
        self.assertEqual(sequence, 2)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        self.assertIsNone(hub.wait_next(sequence, timeout=0.001))
        hub.close()
        self.assertIsNone(hub.wait_next(sequence, timeout=0.001))


if __name__ == "__main__":
    unittest.main()
