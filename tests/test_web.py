import json
import unittest
from urllib.request import Request, urlopen

import numpy as np

from track_eye.web import FrameHub, WebUIServer


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


class WebActionTests(unittest.TestCase):
    def test_json_action_dispatches_to_callback(self):
        hub = FrameHub()
        received = []
        server = WebUIServer(
            hub,
            "127.0.0.1",
            0,
            lambda: {"healthy": True},
            action_callbacks={"/output/gain": lambda body: received.append(body) or {"updated": True}},
        )
        try:
            server.start()
            port = server.httpd.server_address[1]
            request = Request(
                f"http://127.0.0.1:{port}/output/gain",
                data=json.dumps({"down": 4.2}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2.0) as response:
                self.assertEqual(json.load(response), {"updated": True})
            self.assertEqual(received, [{"down": 4.2}])
            hub.update(np.zeros((8, 8, 3), dtype=np.uint8))
            with urlopen(f"http://127.0.0.1:{port}/frame.jpg?after=0", timeout=2.0) as response:
                self.assertEqual(response.headers["X-Frame-Sequence"], "1")
                self.assertTrue(response.read().startswith(b"\xff\xd8"))
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
