import unittest

from track_eye.output import EyeNeutral, OutputCalibration, OutputGain, scale_tracking_result
from track_eye.tracker import EyeSignal, TrackingResult


class OutputGainTests(unittest.TestCase):
    def test_directional_gains_and_neutral_apply_after_raw_result(self):
        raw = TrackingResult(
            timestamp_ns=123,
            face_detected=True,
            eyes=(
                EyeSignal("left", 0.30, -0.30, 0.30, -0.30),
                EyeSignal("right", -0.20, 0.20, -0.20, 0.20),
            ),
            inference_ms=4.5,
        )
        calibration = OutputCalibration(
            OutputGain(left=2.0, right=3.0, up=2.5, down=3.5),
            (EyeNeutral("left", 0.05, -0.10), EyeNeutral("right", -0.05, 0.10)),
        )
        output = scale_tracking_result(raw, calibration)
        self.assertEqual((raw.eyes[0].x, raw.eyes[0].y), (0.30, -0.30))
        self.assertAlmostEqual(output.eyes[0].x, 0.75)
        self.assertAlmostEqual(output.eyes[0].y, -0.50)
        self.assertAlmostEqual(output.eyes[1].x, -0.30)
        self.assertAlmostEqual(output.eyes[1].y, 0.35)

    def test_soft_limit_preserves_center_and_saturates_extremes(self):
        raw = TrackingResult(
            123,
            True,
            (
                EyeSignal("left", 0.2, 0.2, 0.2, 0.2),
                EyeSignal("right", 10.0, 10.0, 10.0, 10.0),
            ),
            4.5,
        )
        output = scale_tracking_result(raw)
        self.assertAlmostEqual(output.eyes[0].x, 0.6)
        self.assertAlmostEqual(output.eyes[0].y, 0.75)
        self.assertGreater(output.eyes[1].x, 1.0)
        self.assertLessEqual(output.eyes[1].x, 1.5)
        self.assertLessEqual(output.eyes[1].y, 1.5)

    def test_no_face_stays_no_face_at_output_boundary(self):
        raw = TrackingResult(123, False, None, 4.5)
        output = scale_tracking_result(raw)
        self.assertFalse(output.face_detected)
        self.assertIsNone(output.eyes)


if __name__ == "__main__":
    unittest.main()
