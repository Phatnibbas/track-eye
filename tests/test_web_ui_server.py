import unittest

import numpy as np

from web_ui_server import FrameHub, render_index_html


class WebUIServerTests(unittest.TestCase):
    def test_render_index_html_contains_camera_and_status_ws(self):
        html = render_index_html(ws_port=8765)

        self.assertIn("/stream.mjpg", html)
        self.assertIn("new WebSocket", html)
        self.assertIn("ws://", html)
        self.assertIn("Gaze Eye Control", html)

    def test_frame_hub_encodes_latest_jpeg(self):
        hub = FrameHub()
        frame = np.zeros((32, 32, 3), dtype=np.uint8)
        hub.update(frame)

        jpeg = hub.latest_jpeg()

        self.assertIsInstance(jpeg, bytes)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        self.assertTrue(jpeg.endswith(b"\xff\xd9"))


if __name__ == "__main__":
    unittest.main()
