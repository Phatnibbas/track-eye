import unittest

from servo_mapper import SingleEyeServoMapper, SingleEyeServoConfig


class SingleEyeServoMapperTests(unittest.TestCase):
    def test_maps_gaze_to_calibrated_single_eye_angles(self):
        mapper = SingleEyeServoMapper(
            SingleEyeServoConfig(
                pan_neutral_deg=90,
                pan_min_deg=55,
                pan_max_deg=125,
                pan_gain_deg=35,
                pan_invert=True,
                tilt_neutral_deg=80,
                tilt_min_deg=50,
                tilt_max_deg=110,
                tilt_gain_deg=30,
                tilt_invert=True,
                smoothing_alpha=1.0,
                max_step_deg=999,
            )
        )

        left_up = mapper.update(-1.0, -1.0, 0.8, True, "hybrid-fallback", False)
        right_down = mapper.update(1.0, 1.0, 0.8, True, "hybrid-fallback", False)

        self.assertEqual((left_up.pan_deg, left_up.tilt_deg), (125.0, 110.0))
        self.assertEqual((right_down.pan_deg, right_down.tilt_deg), (55.0, 50.0))

    def test_holds_on_bad_tracking_and_returns_neutral_on_calibration(self):
        mapper = SingleEyeServoMapper(SingleEyeServoConfig(smoothing_alpha=1.0, max_step_deg=999))
        first = mapper.update(-1.0, 0.0, 0.8, True, "hybrid-fallback", False)
        held = mapper.update(1.0, 1.0, 0.1, True, "hybrid-fallback", False)
        neutral = mapper.update(1.0, 1.0, 0.8, True, "hybrid-fallback", True)

        self.assertEqual(held.gate_state, "hold")
        self.assertEqual((held.pan_deg, held.tilt_deg), (first.pan_deg, first.tilt_deg))
        self.assertEqual(neutral.gate_state, "neutral")
        self.assertEqual((neutral.pan_deg, neutral.tilt_deg), (90.0, 80.0))


if __name__ == "__main__":
    unittest.main()
