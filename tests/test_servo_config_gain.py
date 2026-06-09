import unittest

from main import DEFAULT_CONFIG_PATH, load_config
from servo_mapper import SingleEyeServoConfig


class ServoConfigGainTests(unittest.TestCase):
    def test_config_matches_four_servo_mechanical_limits(self):
        config = load_config(DEFAULT_CONFIG_PATH)
        servo_config = SingleEyeServoConfig.from_dict(config["servo"])

        self.assertEqual(servo_config.pan_neutral_deg, 90.0)
        self.assertEqual(servo_config.pan_min_deg, 50.0)
        self.assertEqual(servo_config.pan_max_deg, 130.0)
        self.assertEqual(servo_config.pan_gain_deg, 40.0)
        self.assertEqual(servo_config.tilt_neutral_deg, 0.0)
        self.assertEqual(servo_config.tilt_min_deg, 0.0)
        self.assertEqual(servo_config.tilt_max_deg, 50.0)
        self.assertEqual(servo_config.tilt_gain_deg, 50.0)


if __name__ == "__main__":
    unittest.main()
