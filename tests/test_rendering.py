import unittest

from track_eye.output import OutputGain, scale_tracking_result
from track_eye.tracker import EyeSignal, TrackingResult


class OutputGainTests(unittest.TestCase):
    def test_directional_gains_apply_after_raw_tracker_result(self):
        raw = TrackingResult(
            timestamp_ns=123,
            face_detected=True,
            eyes=(
                EyeSignal("left", 0.25, -0.4, 0.25, -0.4),
                EyeSignal("right", -0.5, 0.6, -0.5, 0.6),
            ),
            inference_ms=4.5,
        )
        output = scale_tracking_result(raw, OutputGain())
        self.assertEqual(OutputGain(), OutputGain(3.0, 2.5, 3.75))
        self.assertEqual((raw.eyes[0].x, raw.eyes[0].y), (0.25, -0.4))
        self.assertEqual((output.eyes[0].x, output.eyes[0].y), (0.75, -1.0))
        self.assertAlmostEqual(output.eyes[1].x, -1.5)
        self.assertAlmostEqual(output.eyes[1].y, 2.25)

    def test_no_face_stays_no_face_at_output_boundary(self):
        raw = TrackingResult(123, False, None, 4.5)
        output = scale_tracking_result(raw)
        self.assertFalse(output.face_detected)
        self.assertIsNone(output.eyes)


if __name__ == "__main__":
    unittest.main()
