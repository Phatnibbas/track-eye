import unittest

from track_eye.rendering import DISPLAY_DOWN_GAIN, GAUGE_GAIN_H, GAUGE_GAIN_V, apply_display_down_gain


class RenderingGainTests(unittest.TestCase):
    def test_requested_directional_display_gains(self):
        self.assertEqual(GAUGE_GAIN_H, 2.0)
        self.assertEqual(GAUGE_GAIN_V, 2.5)
        self.assertAlmostEqual(GAUGE_GAIN_V * DISPLAY_DOWN_GAIN, 3.0)
        self.assertAlmostEqual(apply_display_down_gain(-1.0) * GAUGE_GAIN_V, -2.5)
        self.assertAlmostEqual(apply_display_down_gain(1.0) * GAUGE_GAIN_V, 3.0)


if __name__ == "__main__":
    unittest.main()
